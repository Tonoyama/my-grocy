#!/usr/bin/env node
import process from 'node:process';

const OPENAI_URL = 'https://api.openai.com/v1/responses';
const DEFAULT_MODEL = 'gpt-4.1-mini';
const DEFAULT_MCP_URL = 'http://localhost:8080/mcp';

const rawArgs = process.argv.slice(2);
const dryRun = rawArgs.includes('--dry-run');
const inputText = rawArgs.filter((arg) => !arg.startsWith('--')).join(' ').trim() || await readStdin();

if (!inputText) {
  console.error('Usage: node mcp-grocy-api/scripts/nl-register.mjs "Milk 2 bottles 2024-12-31 198"');
  process.exit(1);
}

const openaiKey = process.env.OPENAI_API_KEY;
if (!openaiKey) {
  console.error('Missing OPENAI_API_KEY environment variable.');
  process.exit(1);
}

const model = process.env.OPENAI_MODEL || DEFAULT_MODEL;
const mcpUrl = process.env.MCP_HTTP_URL || DEFAULT_MCP_URL;

const parsed = await parseWithOpenAI({
  inputText,
  apiKey: openaiKey,
  model
});

const normalized = normalizeParsed(parsed);
const mcp = createMcpClient(mcpUrl);

await mcp.listTools();

const { product, locationId, storeId } = await findOrCreateProduct(mcp, normalized);

if (dryRun) {
  console.log(JSON.stringify({
    action: normalized.action,
    product,
    resolved: { locationId, storeId },
    input: normalized
  }, null, 2));
  process.exit(0);
}

const result = await applyAction(mcp, normalized, product, { locationId, storeId });
console.log(JSON.stringify(result, null, 2));

function createMcpClient(url) {
  let sessionId = null;
  let initialized = false;

  async function request(body) {
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream'
    };

    if (sessionId) {
      headers['Mcp-Session-Id'] = sessionId;
    }

    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });

    const contentType = response.headers.get('content-type') || '';
    const responseText = await response.text().catch(() => '');

    if (!response.ok) {
      throw new Error(`MCP request failed (${response.status}): ${responseText || response.statusText}`);
    }

    const nextSession = response.headers.get('mcp-session-id');
    if (nextSession) {
      sessionId = nextSession;
    }

    if (contentType.includes('text/event-stream')) {
      return parseSsePayload(responseText);
    }

    return responseText ? JSON.parse(responseText) : {};
  }

  async function listTools() {
    await ensureInitialized();
    return request({
      jsonrpc: '2.0',
      id: `tools-list-${Date.now()}`,
      method: 'tools/list'
    });
  }

  async function callTool(name, args = {}) {
    await ensureInitialized();
    const payload = {
      jsonrpc: '2.0',
      id: `tools-call-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      method: 'tools/call',
      params: {
        name,
        arguments: args
      }
    };

    const response = await request(payload);
    if (response.error) {
      throw new Error(response.error.message || 'MCP tool error');
    }

    return response.result;
  }

  async function ensureInitialized() {
    if (initialized) return;

    await request({
      jsonrpc: '2.0',
      id: `init-${Date.now()}`,
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        clientInfo: {
          name: 'nl-register',
          version: '0.1.0'
        },
        capabilities: {
          tools: {},
          resources: {},
          prompts: {}
        }
      }
    });

    await request({
      jsonrpc: '2.0',
      method: 'client/initialized'
    });

    initialized = true;
  }

  return {
    listTools,
    callTool
  };
}

function parseSsePayload(payload) {
  const lines = payload.split(/\r?\n/);
  const dataLines = lines.filter((line) => line.startsWith('data: '));
  const last = dataLines[dataLines.length - 1];
  if (!last) {
    return {};
  }
  const jsonText = last.replace(/^data:\s*/, '');
  return JSON.parse(jsonText);
}

async function findOrCreateProduct(mcp, parsed) {
  const products = await callAndParseJson(mcp, 'get_products', {});
  const matched = findByName(products, parsed.name);
  if (matched) {
    const resolved = await resolveLocationAndStore(mcp, parsed, {
      fallbackLocationId: matched.location_id
    });
    return { product: matched, ...resolved };
  }

  const locations = await callAndParseJson(mcp, 'get_locations', {});
  const quantityUnits = await callAndParseJson(mcp, 'get_quantity_units', {});
  const shoppingLocations = await callAndParseJson(mcp, 'get_shopping_locations', {});

  const location = parsed.location
    ? findByName(locations, parsed.location)
    : locations[0];
  const quantityUnit = quantityUnits[0];
  const shoppingLocation = parsed.store
    ? findByName(shoppingLocations, parsed.store)
    : null;

  if (!location || !quantityUnit) {
    throw new Error('Could not resolve default location or quantity unit for product creation.');
  }

  const body = {
    name: parsed.name,
    location_id: Number(location.id),
    qu_id_purchase: Number(quantityUnit.id),
    qu_id_stock: Number(quantityUnit.id)
  };

  if (shoppingLocation?.id) {
    body.shopping_location_id = Number(shoppingLocation.id);
  }

  const created = await callAndParseJson(mcp, 'call_grocy_api', {
    endpoint: 'objects/products',
    method: 'POST',
    body
  });

  return {
    product: created,
    locationId: Number(location.id),
    storeId: shoppingLocation?.id ? Number(shoppingLocation.id) : undefined
  };
}

async function applyAction(mcp, parsed, product, { locationId, storeId }) {
  switch (parsed.action) {
    case 'shopping_list':
      return callAndParseJson(mcp, 'add_shopping_list_item', {
        productId: Number(product.id),
        amount: parsed.amount,
        shoppingListId: parsed.shoppingListId || 1,
        note: parsed.note || undefined
      });
    case 'inventory':
      return callAndParseJson(mcp, 'inventory_product', {
        productId: Number(product.id),
        newAmount: parsed.amount,
        bestBeforeDate: parsed.bestBeforeDate || undefined,
        locationId: locationId || parsed.locationId || undefined,
        note: parsed.note || undefined
      });
    case 'create_only':
      return { createdProductId: product.id };
    case 'purchase':
    default:
      return callAndParseJson(mcp, 'purchase_product', {
        productId: Number(product.id),
        amount: parsed.amount,
        bestBeforeDate: parsed.bestBeforeDate || undefined,
        price: parsed.price || undefined,
        storeId: storeId || parsed.storeId || undefined,
        locationId: locationId || parsed.locationId || undefined,
        note: parsed.note || undefined
      });
  }
}

async function callAndParseJson(mcp, toolName, args) {
  const result = await mcp.callTool(toolName, args);
  const rawText = result?.content?.map((item) => item.text || '').join('') || '';

  if (!rawText.trim()) {
    return result;
  }

  try {
    const parsed = JSON.parse(rawText);
    if (parsed?.response?.body) {
      return parsed.response.body;
    }
    return parsed;
  } catch (error) {
    return { raw: rawText };
  }
}

function findByName(list, name) {
  if (!Array.isArray(list)) return null;
  const needle = normalizeName(name);
  return list.find((item) => normalizeName(item.name) === needle) ||
    list.find((item) => normalizeName(item.name).includes(needle)) ||
    null;
}

function normalizeName(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/[^\p{L}\p{N}]/gu, '');
}

function normalizeParsed(parsed) {
  const amount = typeof parsed.amount === 'number' && parsed.amount > 0 ? parsed.amount : 1;
  const action = parsed.action || 'purchase';
  const note = parsed.note || (parsed.unit ? `unit=${parsed.unit}` : undefined);

  return {
    action,
    name: parsed.name,
    amount,
    unit: parsed.unit || undefined,
    bestBeforeDate: parsed.bestBeforeDate || undefined,
    price: typeof parsed.price === 'number' ? parsed.price : undefined,
    location: parsed.location || undefined,
    store: parsed.store || undefined,
    note,
    locationId: parsed.locationId || undefined,
    storeId: parsed.storeId || undefined,
    shoppingListId: parsed.shoppingListId || undefined
  };
}

async function resolveLocationAndStore(mcp, parsed, { fallbackLocationId }) {
  let locationId = parsed.locationId;
  let storeId = parsed.storeId;

  if (!locationId && parsed.location) {
    const locations = await callAndParseJson(mcp, 'get_locations', {});
    const location = findByName(locations, parsed.location);
    if (location?.id) {
      locationId = Number(location.id);
    }
  }

  if (!locationId && fallbackLocationId) {
    locationId = Number(fallbackLocationId);
  }

  if (!storeId && parsed.store) {
    const shoppingLocations = await callAndParseJson(mcp, 'get_shopping_locations', {});
    const shoppingLocation = findByName(shoppingLocations, parsed.store);
    if (shoppingLocation?.id) {
      storeId = Number(shoppingLocation.id);
    }
  }

  return { locationId, storeId };
}

async function parseWithOpenAI({ inputText, apiKey, model }) {
  const body = {
    model,
    input: [
      {
        role: 'system',
        content: [
          'Extract a Grocy registration action from the user text.',
          'Input may be in Japanese; keep product names in the original language.',
          'Return JSON matching the schema, with dates in YYYY-MM-DD.',
          'If the user wants a shopping list entry, set action=shopping_list.',
          'If they want to set exact stock amount, set action=inventory.',
          'If they only want to register the product, set action=create_only.',
          'Otherwise set action=purchase.',
          'Currency is JPY; if a price is provided (e.g. "198円" or "¥198"), set price to the numeric value without symbols.'
        ].join(' ')
      },
      { role: 'user', content: inputText }
    ],
    text: {
      format: {
        type: 'json_schema',
        name: 'grocy_item',
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: {
            action: {
              type: 'string',
              enum: ['purchase', 'inventory', 'shopping_list', 'create_only']
            },
            name: { type: 'string' },
            amount: { type: ['number', 'null'] },
            unit: { type: ['string', 'null'] },
            bestBeforeDate: { type: ['string', 'null'] },
            price: { type: ['number', 'null'] },
            location: { type: ['string', 'null'] },
            store: { type: ['string', 'null'] },
            note: { type: ['string', 'null'] },
            locationId: { type: ['number', 'null'] },
            storeId: { type: ['number', 'null'] },
            shoppingListId: { type: ['number', 'null'] }
          },
          required: [
            'action',
            'name',
            'amount',
            'unit',
            'bestBeforeDate',
            'price',
            'location',
            'store',
            'note',
            'locationId',
            'storeId',
            'shoppingListId'
          ]
        }
      }
    }
  };

  const response = await fetch(OPENAI_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`OpenAI API error (${response.status}): ${text || response.statusText}`);
  }

  const data = await response.json();
  const outputText = data.output_text ||
    data.output?.flatMap((item) => item.content || []).map((item) => item.text || '').join('');

  if (!outputText) {
    throw new Error('OpenAI response missing output text.');
  }

  return JSON.parse(outputText);
}

function readStdin() {
  return new Promise((resolve) => {
    if (process.stdin.isTTY) {
      resolve('');
      return;
    }

    let input = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      input += chunk;
    });
    process.stdin.on('end', () => resolve(input.trim()));
  });
}

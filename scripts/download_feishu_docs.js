#!/usr/bin/env node

const crypto = require('crypto');
const fs = require('fs/promises');
const path = require('path');

const { authStore } = require(
  '/Users/raojiajun/.lark-mcp/node_modules/@larksuiteoapi/lark-mcp/dist/auth/store'
);

const APP_ID = 'cli_aa0f24c73678dcc0';
const API_ROOT = 'https://open.feishu.cn/open-apis';
const OUTPUT_DIR = path.resolve(__dirname, '..', 'downloads', 'feishu');

const DOCUMENTS = [
  {
    title: '六生六世Seedance2.5分镜脚本',
    filename: '六生六世Seedance2.5分镜脚本.md',
    nodeToken: 'MTXywkiPNiCvU8kZrbhc1NJQnc6',
    documentId: 'MkOAdDpR3o8ZzDx8wiBcw8xdnAh',
    sourceUrl: 'https://ecn1exsttmmy.feishu.cn/wiki/MTXywkiPNiCvU8kZrbhc1NJQnc6',
  },
  {
    title: '04 生视频任务进度与查询手册',
    filename: '04-生视频任务进度与查询手册.md',
    nodeToken: 'TBVowWsXOiZ6g7kXXxGcYRmEnXe',
    documentId: 'QBned6jH9oNVNExRp6qcxmO8n4d',
    sourceUrl: 'https://ecn1exsttmmy.feishu.cn/wiki/TBVowWsXOiZ6g7kXXxGcYRmEnXe',
  },
  {
    title: '05 视频质量评分 Skill',
    filename: '05-视频质量评分-Skill.md',
    nodeToken: 'VQnYw8KAPimm4BkIJQbcEQI3nw6',
    documentId: 'TNGudbA0uoYebCxL4nNcNXe8nte',
    sourceUrl: 'https://ecn1exsttmmy.feishu.cn/wiki/VQnYw8KAPimm4BkIJQbcEQI3nw6',
  },
];

async function fetchRawContent(accessToken, documentId) {
  const response = await fetch(
    `${API_ROOT}/docx/v1/documents/${encodeURIComponent(documentId)}/raw_content`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  const payload = await response.json();

  if (!response.ok || payload.code !== 0 || typeof payload.data?.content !== 'string') {
    throw new Error(`Failed to download ${documentId}: ${payload.code ?? response.status} ${payload.msg ?? ''}`);
  }
  return payload.data.content;
}

async function main() {
  const accessToken = await authStore.getLocalAccessToken(APP_ID);
  if (!accessToken) {
    throw new Error('No Feishu user access token found. Run lark-mcp login first.');
  }

  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  const fetchedAt = new Date().toISOString();
  const index = [];

  for (const document of DOCUMENTS) {
    const content = await fetchRawContent(accessToken, document.documentId);
    const outputPath = path.join(OUTPUT_DIR, document.filename);
    await fs.writeFile(outputPath, content, 'utf8');

    const bytes = Buffer.byteLength(content, 'utf8');
    const sha256 = crypto.createHash('sha256').update(content).digest('hex');
    index.push({ ...document, fetchedAt, bytes, sha256 });
    console.log(`${document.filename}\t${bytes} bytes\t${sha256}`);
  }

  await fs.writeFile(
    path.join(OUTPUT_DIR, 'index.json'),
    `${JSON.stringify({ fetchedAt, documents: index }, null, 2)}\n`,
    'utf8'
  );
}

main().then(
  () => process.exit(0),
  (error) => {
    console.error(error.message);
    process.exit(1);
  }
);

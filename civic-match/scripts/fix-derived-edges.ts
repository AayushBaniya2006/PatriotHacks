#!/usr/bin/env tsx
/**
 * Fix issue #7: Mark deterministic graph edges as derived
 * 
 * All edges with kind=fact but no sources are structural/deterministic
 * (running_for, holds, elects) that derive from the elections file.
 * Add derived: true marker so the UI can explain these.
 */

import fs from 'fs';
import path from 'path';

const GRAPH_PATH = path.join(process.cwd(), 'data/graph/graph.json');

interface Edge {
  source: string;
  target: string;
  relationship: string | null;
  kind: string;
  sources: Array<{ title: string; url: string; publisher?: string }>;
  derived?: boolean;
}

interface Graph {
  nodes: any[];
  edges: Edge[];
}

// Relationship types that are deterministic/structural
const DERIVED_RELATIONSHIPS = new Set([
  'running_for',
  'holds',
  'elects',
  'succeeds',
  null // null relationship is also structural (e.g., race -> office)
]);

function fixDerivedEdges() {
  console.log('Reading graph...');
  const graph: Graph = JSON.parse(fs.readFileSync(GRAPH_PATH, 'utf8'));
  
  let fixedCount = 0;
  
  for (const edge of graph.edges) {
    // If it's a fact with no sources and is a structural relationship
    if (edge.kind === 'fact' && edge.sources.length === 0) {
      // Add derived marker
      edge.derived = true;
      fixedCount++;
    }
  }
  
  console.log(`Marked ${fixedCount} edges as derived`);
  
  // Write back
  fs.writeFileSync(GRAPH_PATH, JSON.stringify(graph, null, 2) + '\n');
  console.log('✓ Graph updated');
}

fixDerivedEdges();

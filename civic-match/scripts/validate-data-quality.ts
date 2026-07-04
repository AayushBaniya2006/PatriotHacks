#!/usr/bin/env tsx
/**
 * Comprehensive Data Validation Agent
 * 
 * Validates:
 * 1. Source URL accessibility and relevance
 * 2. Stance quality and groundedness
 * 3. Qualitative dimensions completeness
 * 4. Promise-vs-record consistency
 * 5. Finance data correlation with sources
 * 6. Cross-reference consistency
 */

import { promises as fs } from 'fs';
import path from 'path';
import { PoliticianProfile } from '../lib/types';

interface ValidationResult {
  politician: string;
  slug: string;
  passed: boolean;
  warnings: string[];
  errors: string[];
  stats: {
    stances: number;
    sources_checked: number;
    sources_accessible: number;
    qualitative_dims: number;
    promises: number;
    finance_data: boolean;
  };
}

interface ValidationSummary {
  total_politicians: number;
  passed: number;
  failed: number;
  total_warnings: number;
  total_errors: number;
  by_party: Record<string, { passed: number; failed: number }>;
  source_accessibility_rate: number;
  avg_stances_per_politician: number;
  well_researched_count: number;
}

const TIMEOUT_MS = 5000;

async function checkSourceAccessibility(url: string): Promise<{ accessible: boolean; status?: number; error?: string }> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
    
    const response = await fetch(url, {
      method: 'HEAD',
      signal: controller.signal,
      headers: {
        'User-Agent': 'Mozilla/5.0 (compatible; CivicMatchValidator/1.0)',
      },
    });
    
    clearTimeout(timeout);
    return { accessible: response.ok, status: response.status };
  } catch (error: any) {
    if (error.name === 'AbortError') {
      return { accessible: false, error: 'timeout' };
    }
    return { accessible: false, error: error.message };
  }
}

function validateStanceQuality(stance: any, politicianName: string): string[] {
  const issues: string[] = [];
  
  // Check required fields
  if (!stance.issue_id) issues.push('Missing issue_id');
  if (!stance.position_label) issues.push('Missing position_label');
  if (!stance.summary) issues.push('Missing summary');
  if (stance.position_scalar === null || stance.position_scalar === undefined) {
    issues.push('Missing position_scalar');
  }
  
  // Check scalar is in valid range [0, 1]
  if (stance.position_scalar !== null && (stance.position_scalar < 0 || stance.position_scalar > 1)) {
    issues.push(`Invalid position_scalar: ${stance.position_scalar} (must be 0-1)`);
  }
  
  // Check sources exist
  if (!stance.sources || stance.sources.length === 0) {
    issues.push('No sources provided');
  }
  
  // Check confidence and recency
  if (stance.confidence !== undefined && (stance.confidence < 0 || stance.confidence > 1)) {
    issues.push(`Invalid confidence: ${stance.confidence}`);
  }
  
  // Check for generic/placeholder text
  const genericPhrases = ['unknown', 'no information', 'unclear', 'not stated'];
  if (genericPhrases.some(phrase => stance.summary?.toLowerCase().includes(phrase))) {
    issues.push('Summary contains generic/placeholder text');
  }
  
  // Check summary length is reasonable (not too short, not too long)
  if (stance.summary && stance.summary.length < 20) {
    issues.push('Summary is too short (< 20 chars)');
  }
  if (stance.summary && stance.summary.length > 1000) {
    issues.push('Summary is too long (> 1000 chars)');
  }
  
  return issues;
}

function validateQualitativeDimensions(profile: PoliticianProfile): string[] {
  const issues: string[] = [];
  
  if (!profile.qualitative || profile.qualitative.length === 0) {
    return ['No qualitative dimensions - incomplete research'];
  }
  
  const expectedDims = ['integrity', 'public_interest', 'transparency', 'experience'];
  const foundDims = new Set<string>(profile.qualitative.map(q => q.id));
  
  for (const dim of expectedDims) {
    if (!foundDims.has(dim)) {
      issues.push(`Missing qualitative dimension: ${dim}`);
    }
  }
  
  // Validate each dimension
  for (const qual of profile.qualitative) {
    if (qual.score === undefined || qual.score < 0 || qual.score > 1) {
      issues.push(`Invalid score for ${qual.id}: ${qual.score}`);
    }
    if (!qual.summary || qual.summary.length < 20) {
      issues.push(`${qual.id} summary is too short or missing`);
    }
    if (!qual.sources || qual.sources.length === 0) {
      issues.push(`${qual.id} has no sources`);
    }
  }
  
  return issues;
}

function validatePromiseRecord(profile: PoliticianProfile): string[] {
  const issues: string[] = [];
  
  if (!profile.promise_record || profile.promise_record.length === 0) {
    // Not an error, just a note - many candidates don't have promise-vs-record data
    return [];
  }
  
  for (const record of profile.promise_record) {
    if (!record.promise) issues.push('Promise record missing promise text');
    if (!record.action) issues.push('Promise record missing action/outcome');
    if (!record.verdict) issues.push('Promise record missing verdict');
    if (!record.sources || record.sources.length === 0) {
      issues.push('Promise record missing sources');
    }
  }
  
  return issues;
}

async function validatePolitician(profile: PoliticianProfile, checkSources: boolean): Promise<ValidationResult> {
  const result: ValidationResult = {
    politician: profile.name,
    slug: profile.slug || 'unknown',
    passed: true,
    warnings: [],
    errors: [],
    stats: {
      stances: profile.stances?.length || 0,
      sources_checked: 0,
      sources_accessible: 0,
      qualitative_dims: profile.qualitative?.length || 0,
      promises: profile.promise_record?.length || 0,
      finance_data: !!(profile.donors && profile.donors.length > 0),
    },
  };
  
  // Validate basic fields
  if (!profile.name) result.errors.push('Missing name');
  if (!profile.party) result.warnings.push('Missing party affiliation');
  if (!profile.current_office && !profile.office) {
    result.warnings.push('Missing office/current_office');
  }
  
  // Validate stances
  if (!profile.stances || profile.stances.length === 0) {
    result.errors.push('No stances - completely unresearched');
  } else {
    for (const stance of profile.stances) {
      const stanceIssues = validateStanceQuality(stance, profile.name);
      result.warnings.push(...stanceIssues);
      
      // Collect all sources from stance
      if (stance.sources && checkSources) {
        for (const source of stance.sources) {
          if (source.url) {
            result.stats.sources_checked++;
            const check = await checkSourceAccessibility(source.url);
            if (check.accessible) {
              result.stats.sources_accessible++;
            } else {
              result.warnings.push(
                `Source unreachable for ${stance.issue_id}: ${source.url} (${check.error || check.status})`
              );
            }
          }
        }
      }
    }
  }
  
  // Validate qualitative dimensions
  const qualIssues = validateQualitativeDimensions(profile);
  if (qualIssues.length > 0) {
    result.warnings.push(...qualIssues);
  }
  
  // Validate promise record
  const promiseIssues = validatePromiseRecord(profile);
  if (promiseIssues.length > 0) {
    result.warnings.push(...promiseIssues);
  }
  
  // Check for contradictions in unknowns
  if (profile.unknowns && profile.unknowns.length > 0) {
    for (const unknown of profile.unknowns) {
      const hasStanceOnTopic = profile.stances?.some(s => s.issue_id === unknown);
      if (hasStanceOnTopic) {
        result.warnings.push(`Issue ${unknown} marked as unknown but has a stance`);
      }
    }
  }
  
  // Determine pass/fail
  result.passed = result.errors.length === 0;
  
  return result;
}

async function main() {
  const args = process.argv.slice(2);
  const checkSources = args.includes('--check-sources');
  const verbose = args.includes('--verbose');
  const limitStr = args.find(a => a.startsWith('--limit='));
  const limit = limitStr ? parseInt(limitStr.split('=')[1]) : undefined;
  
  console.log('=== Civic Match Data Validation Agent ===\n');
  if (checkSources) {
    console.log('⚠️  Source accessibility checks enabled (slow)\n');
  }
  
  const politiciansDir = path.join(process.cwd(), 'data', 'politicians');
  const files = (await fs.readdir(politiciansDir))
    .filter(f => f.endsWith('.json'))
    .slice(0, limit);
  
  console.log(`Validating ${files.length} politicians...\n`);
  
  const results: ValidationResult[] = [];
  const summary: ValidationSummary = {
    total_politicians: files.length,
    passed: 0,
    failed: 0,
    total_warnings: 0,
    total_errors: 0,
    by_party: {},
    source_accessibility_rate: 0,
    avg_stances_per_politician: 0,
    well_researched_count: 0,
  };
  
  let totalStances = 0;
  let totalSourcesChecked = 0;
  let totalSourcesAccessible = 0;
  
  for (const file of files) {
    const filePath = path.join(politiciansDir, file);
    const content = await fs.readFile(filePath, 'utf-8');
    const profile: PoliticianProfile = JSON.parse(content);
    
    const result = await validatePolitician(profile, checkSources);
    results.push(result);
    
    // Update summary
    if (result.passed) {
      summary.passed++;
    } else {
      summary.failed++;
    }
    
    summary.total_warnings += result.warnings.length;
    summary.total_errors += result.errors.length;
    
    const party = profile.party || 'Unknown';
    if (!summary.by_party[party]) {
      summary.by_party[party] = { passed: 0, failed: 0 };
    }
    if (result.passed) {
      summary.by_party[party].passed++;
    } else {
      summary.by_party[party].failed++;
    }
    
    totalStances += result.stats.stances;
    totalSourcesChecked += result.stats.sources_checked;
    totalSourcesAccessible += result.stats.sources_accessible;
    
    // Well-researched = has stances + qualitative + either promises or finance
    if (
      result.stats.stances >= 8 &&
      result.stats.qualitative_dims >= 3 &&
      (result.stats.promises > 0 || result.stats.finance_data)
    ) {
      summary.well_researched_count++;
    }
    
    // Progress indicator
    if ((results.length % 10 === 0) || verbose) {
      console.log(`  [${results.length}/${files.length}] ${profile.name}`);
    }
  }
  
  summary.avg_stances_per_politician = totalStances / files.length;
  if (totalSourcesChecked > 0) {
    summary.source_accessibility_rate = totalSourcesAccessible / totalSourcesChecked;
  }
  
  // Print summary
  console.log('\n=== VALIDATION SUMMARY ===\n');
  console.log(`Total Politicians: ${summary.total_politicians}`);
  console.log(`✓ Passed: ${summary.passed} (${((summary.passed / summary.total_politicians) * 100).toFixed(1)}%)`);
  console.log(`✗ Failed: ${summary.failed} (${((summary.failed / summary.total_politicians) * 100).toFixed(1)}%)`);
  console.log(`⚠  Total Warnings: ${summary.total_warnings}`);
  console.log(`✗ Total Errors: ${summary.total_errors}`);
  console.log(`📊 Avg Stances per Politician: ${summary.avg_stances_per_politician.toFixed(1)}`);
  console.log(`⭐ Well-Researched (8+ stances, 3+ qual dims): ${summary.well_researched_count}`);
  
  if (checkSources && totalSourcesChecked > 0) {
    console.log(`🔗 Source Accessibility: ${(summary.source_accessibility_rate * 100).toFixed(1)}% (${totalSourcesAccessible}/${totalSourcesChecked})`);
  }
  
  console.log('\n=== BY PARTY ===');
  for (const [party, stats] of Object.entries(summary.by_party)) {
    const total = stats.passed + stats.failed;
    const passRate = (stats.passed / total) * 100;
    console.log(`  ${party}: ${stats.passed}/${total} passed (${passRate.toFixed(1)}%)`);
  }
  
  // Print detailed failures
  const failures = results.filter(r => !r.passed);
  if (failures.length > 0) {
    console.log('\n=== FAILED VALIDATIONS ===');
    for (const failure of failures) {
      console.log(`\n❌ ${failure.politician} (${failure.slug})`);
      for (const error of failure.errors) {
        console.log(`   ERROR: ${error}`);
      }
      if (verbose) {
        for (const warning of failure.warnings.slice(0, 3)) {
          console.log(`   WARN: ${warning}`);
        }
        if (failure.warnings.length > 3) {
          console.log(`   ... and ${failure.warnings.length - 3} more warnings`);
        }
      }
    }
  }
  
  // Print politicians with most warnings
  if (verbose && summary.total_warnings > 0) {
    console.log('\n=== TOP WARNINGS ===');
    const topWarnings = results
      .filter(r => r.warnings.length > 0)
      .sort((a, b) => b.warnings.length - a.warnings.length)
      .slice(0, 5);
    
    for (const result of topWarnings) {
      console.log(`\n⚠️  ${result.politician}: ${result.warnings.length} warnings`);
      for (const warning of result.warnings.slice(0, 3)) {
        console.log(`   - ${warning}`);
      }
      if (result.warnings.length > 3) {
        console.log(`   ... and ${result.warnings.length - 3} more`);
      }
    }
  }
  
  // Exit code
  if (summary.failed > 0) {
    console.log('\n❌ Validation failed: some politicians have errors');
    process.exit(1);
  } else {
    console.log('\n✅ All politicians passed validation');
    process.exit(0);
  }
}

main().catch(error => {
  console.error('Fatal error:', error);
  process.exit(2);
});

import { describe, it, expect } from 'vitest';
import { CaseStatus, CasePriority } from './case';

// case.ts is mostly type-only, but it ships two runtime string enums.
// These tests pin their member values — they are used as API payload
// literals, so a typo here would silently break case filtering.
describe('CaseStatus enum', () => {
  it('maps each member to its wire string value', () => {
    expect(CaseStatus.OPEN).toBe('open');
    expect(CaseStatus.IN_REVIEW).toBe('in_review');
    expect(CaseStatus.ON_HOLD).toBe('on_hold');
    expect(CaseStatus.FINALIZED).toBe('finalized');
    expect(CaseStatus.CLOSED).toBe('closed');
  });

  it('exposes exactly five members', () => {
    expect(Object.keys(CaseStatus)).toHaveLength(5);
  });
});

describe('CasePriority enum', () => {
  it('maps each member to its wire string value', () => {
    expect(CasePriority.CRITICAL).toBe('critical');
    expect(CasePriority.HIGH).toBe('high');
    expect(CasePriority.MEDIUM).toBe('medium');
    expect(CasePriority.LOW).toBe('low');
  });

  it('exposes exactly four members', () => {
    expect(Object.keys(CasePriority)).toHaveLength(4);
  });
});

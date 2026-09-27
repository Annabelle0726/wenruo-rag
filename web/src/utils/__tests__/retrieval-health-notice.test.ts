import i18n from '@/locales/config';
import { toast } from 'sonner';

import {
  noticeForRetrievalHealth,
  notifyRetrievalHealth,
  resetRetrievalNoticeDedup,
} from '../retrieval-health-notice';

jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
    warning: jest.fn(),
    info: jest.fn(),
    success: jest.fn(),
  },
}));

const warningToast = toast.warning as jest.Mock;
const errorToast = toast.error as jest.Mock;

const health = (overrides: Record<string, unknown> = {}) => ({
  overall: 'degraded',
  evidence_completeness: 'partial',
  degradation_reason: null,
  ...overrides,
});

const referenceWith = (retrievalHealth: unknown) =>
  ({
    chunks: [],
    doc_aggs: [],
    total: 0,
    retrieval_health: retrievalHealth,
  }) as never;

const toastTexts = () =>
  [...warningToast.mock.calls, ...errorToast.mock.calls].map(([text]) => text);

const everyRenderedCharacter = () => JSON.stringify(toastTexts());

beforeEach(() => {
  jest.clearAllMocks();
  resetRetrievalNoticeDedup();
});

describe('the approved copy (pinned)', () => {
  it('says exactly what was approved', () => {
    expect(i18n.t('message.retrievalNotice.degraded')).toBe(
      'Semantic search is temporarily degraded; this answer may be incomplete.',
    );
    expect(i18n.t('message.retrievalNotice.failed')).toBe(
      'Retrieval failed, so no knowledge base content was used and this answer may be inaccurate.',
    );
  });

  it('claims no fallback mechanism, because none is observable', () => {
    for (const text of [
      i18n.t('message.retrievalNotice.degraded'),
      i18n.t('message.retrievalNotice.failed'),
    ]) {
      expect(text).not.toMatch(/text search/i);
      expect(text).not.toMatch(/switched/i);
      expect(text).not.toMatch(/fall ?back/i);
    }
  });
});

describe('disclosure mapping', () => {
  it('C1: a full retrieval is silent', () => {
    expect(noticeForRetrievalHealth(health({ overall: 'full' }))).toBeNull();
    expect(notifyRetrievalHealth(referenceWith(health({ overall: 'full' })))).toBeNull();
    expect(warningToast).not.toHaveBeenCalled();
    expect(errorToast).not.toHaveBeenCalled();
  });

  it('C2: a missing or malformed signal stays silent instead of inventing a state', () => {
    expect(noticeForRetrievalHealth(undefined)).toBeNull();
    expect(noticeForRetrievalHealth(null)).toBeNull();
    expect(noticeForRetrievalHealth({} as never)).toBeNull();
    expect(noticeForRetrievalHealth('degraded' as never)).toBeNull();
    expect(notifyRetrievalHealth(undefined)).toBeNull();
    expect(notifyRetrievalHealth({ chunks: [], doc_aggs: [], total: 0 } as never)).toBeNull();
    expect(warningToast).not.toHaveBeenCalled();
    expect(errorToast).not.toHaveBeenCalled();
  });

  it('C3: quota exhaustion uses the single honest degraded sentence', () => {
    const signal = health({
      overall: 'degraded',
      degradation_reason: 'EMBEDDING_QUOTA_EXHAUSTED',
      evidence_completeness: 'partial',
    });

    expect(noticeForRetrievalHealth(signal)).toBe('degraded');
    expect(notifyRetrievalHealth(referenceWith(signal), 'answer-1')).toBe('degraded');

    expect(warningToast).toHaveBeenCalledTimes(1);
    expect(warningToast).toHaveBeenCalledWith(
      'Semantic search is temporarily degraded; this answer may be incomplete.',
      expect.objectContaining({ id: 'retrieval-notice-degraded' }),
    );
    // A degradation is information, not an alarm.
    expect(errorToast).not.toHaveBeenCalled();
  });

  it('C3: the reason never changes the wording, in any evidence state', () => {
    for (const completeness of ['partial', 'full', 'insufficient', undefined]) {
      expect(
        noticeForRetrievalHealth(
          health({
            degradation_reason: 'EMBEDDING_QUOTA_EXHAUSTED',
            evidence_completeness: completeness,
          }),
        ),
      ).toBe('degraded');
    }
  });

  it('C4: every other degradation uses the same sentence', () => {
    for (const reason of [
      'STORE_UNAVAILABLE',
      'EMBEDDING_TIMEOUT',
      'PLAN_EMPTY',
      'EMBEDDING_UNAVAILABLE',
      null,
      undefined,
    ]) {
      expect(noticeForRetrievalHealth(health({ degradation_reason: reason }))).toBe('degraded');
    }

    expect(
      notifyRetrievalHealth(referenceWith(health({ degradation_reason: 'STORE_UNAVAILABLE' }))),
    ).toBe('degraded');
    expect(warningToast).toHaveBeenCalledWith(
      'Semantic search is temporarily degraded; this answer may be incomplete.',
      expect.objectContaining({ id: 'retrieval-notice-degraded' }),
    );
  });

  it('C4: the reason detail is never rendered', () => {
    notifyRetrievalHealth(
      referenceWith(health({ degradation_reason: 'STORE_UNAVAILABLE' })),
      'answer-1',
    );

    expect(everyRenderedCharacter()).not.toContain('STORE_UNAVAILABLE');
  });

  it('C6: a failed retrieval gets the explicit failure notice as an error', () => {
    const signal = health({ overall: 'failed', degradation_reason: 'STORE_UNAVAILABLE' });

    expect(noticeForRetrievalHealth(signal)).toBe('failed');
    expect(notifyRetrievalHealth(referenceWith(signal))).toBe('failed');

    expect(errorToast).toHaveBeenCalledTimes(1);
    expect(errorToast).toHaveBeenCalledWith(
      i18n.t('message.retrievalNotice.failed'),
      expect.objectContaining({ id: 'retrieval-notice-failed' }),
    );
    expect(warningToast).not.toHaveBeenCalled();
  });

  it('an unrecognised overall value stays silent rather than rendering itself', () => {
    expect(noticeForRetrievalHealth(health({ overall: 'partially-ok' }))).toBeNull();
    expect(notifyRetrievalHealth(referenceWith(health({ overall: 'partially-ok' })))).toBeNull();
    expect(warningToast).not.toHaveBeenCalled();
  });
});

describe('dedup: one degraded retrieval produces one notice', () => {
  const degradedReference = () =>
    referenceWith(health({ degradation_reason: 'EMBEDDING_QUOTA_EXHAUSTED' }));

  it('five degraded sub-routes arrive as one signal and produce exactly one toast', () => {
    // The backend aggregates every sub-route into ONE retrieval_health object, so the
    // frontend sees a single signal; the assertion is that repeated handling of that
    // same answer cannot stack a second notice.
    expect(notifyRetrievalHealth(degradedReference(), 'answer-1')).toBe('degraded');
    expect(notifyRetrievalHealth(degradedReference(), 'answer-1')).toBeNull();
    expect(notifyRetrievalHealth(degradedReference(), 'answer-1')).toBeNull();

    expect(warningToast).toHaveBeenCalledTimes(1);
    expect(errorToast).not.toHaveBeenCalled();
  });

  it('a later answer of the same kind inside the cooldown window does not stack', () => {
    expect(notifyRetrievalHealth(degradedReference(), 'answer-1')).toBe('degraded');
    expect(notifyRetrievalHealth(degradedReference(), 'answer-2')).toBeNull();

    expect(warningToast).toHaveBeenCalledTimes(1);
  });

  it('a later answer of the same kind after the cooldown is disclosed again', () => {
    const now = jest.spyOn(Date, 'now');

    now.mockReturnValue(1_000_000);
    expect(notifyRetrievalHealth(degradedReference(), 'answer-1')).toBe('degraded');

    now.mockReturnValue(1_000_000 + 10_001);
    expect(notifyRetrievalHealth(degradedReference(), 'answer-2')).toBe('degraded');

    expect(warningToast).toHaveBeenCalledTimes(2);
    now.mockRestore();
  });

  it('different kinds do not suppress each other', () => {
    expect(notifyRetrievalHealth(degradedReference(), 'answer-1')).toBe('degraded');
    expect(notifyRetrievalHealth(referenceWith(health({ overall: 'failed' })), 'answer-2')).toBe(
      'failed',
    );

    expect(warningToast).toHaveBeenCalledTimes(1);
    expect(errorToast).toHaveBeenCalledTimes(1);
  });

  it('a stable toast id is always supplied so an identical notice supersedes its predecessor', () => {
    notifyRetrievalHealth(degradedReference(), 'answer-1');

    const [, options] = warningToast.mock.calls[0];
    expect(options.id).toBe('retrieval-notice-degraded');
    expect(options.duration).toBeGreaterThan(0);
  });
});

describe('security red lines', () => {
  const SECRET_MARKERS = [
    'AQ.Ab8RN6',
    'api_key',
    'generativelanguage.googleapis.com',
    'Traceback',
    'RESOURCE_EXHAUSTED',
    'FAILED_PRECONDITION',
    'stack',
  ];

  it('never renders an enum value, a raw reason or any injected payload', () => {
    const hostileReason =
      'AQ.Ab8RN6LEAK api_key=secret https://generativelanguage.googleapis.com Traceback: 400 FAILED_PRECONDITION RESOURCE_EXHAUSTED stack';

    notifyRetrievalHealth(
      referenceWith(
        health({
          overall: 'degraded',
          degradation_reason: hostileReason,
          evidence_completeness: 'partial',
          // Extra fields a future backend might add must not become renderable either.
          provider_error: hostileReason,
          endpoint: hostileReason,
        }),
      ),
      'answer-1',
    );

    const rendered = everyRenderedCharacter();
    for (const marker of SECRET_MARKERS) {
      expect(rendered).not.toContain(marker);
    }
    // The only text that may appear is the localized constant, verbatim.
    expect(toastTexts()).toEqual([i18n.t('message.retrievalNotice.degraded')]);
  });

  it('never renders the text of an unmapped reason, even one that looks like quota', () => {
    notifyRetrievalHealth(
      referenceWith(health({ degradation_reason: 'EMBEDDING_QUOTA_EXHAUSTED_BUT_FAKE' })),
      'answer-1',
    );

    expect(toastTexts()).toEqual([i18n.t('message.retrievalNotice.degraded')]);
  });

  it('ignores a non-string hostile value such as an Error object', () => {
    expect(
      noticeForRetrievalHealth({
        overall: new Error('boom') as never,
        degradation_reason: { detail: 'boom' } as never,
        evidence_completeness: ['partial'] as never,
      }),
    ).toBeNull();
    expect(warningToast).not.toHaveBeenCalled();
  });
});

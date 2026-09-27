/**
 * C1-C6 user-visible acceptance through the REAL chat stream path.
 *
 * This drives `runChatCompletionStream` - the production SSE driver - with a
 * synthetic terminal frame carrying each `retrieval_health` shape, and asserts
 * what the user actually sees. Only the transport and the store are doubled;
 * the merge, the flush, the notice module, the dedup guard, the i18n lookup and
 * the sonner call are the deployed ones.
 */

jest.mock('../store', () => {
  const store = {
    beginStream: jest.fn(() => true),
    applyAnswer: jest.fn(),
    endStream: jest.fn(),
  };

  return {
    __store: store,
    useChatStreamStore: { getState: () => store },
  };
});

jest.mock('@/services/chat-completion-stream', () => {
  const holder: { chunks: unknown[] } = { chunks: [] };

  return {
    __holder: holder,
    requestChatCompletionStream: jest.fn(async () => ({
      status: 200,
      clone: () => ({
        json: async () => {
          throw new Error('the stream body is not JSON');
        },
      }),
    })),
    parseCompletionEventStream: () =>
      (async function* () {
        for (const chunk of holder.chunks) {
          yield chunk;
        }
      })(),
    readJsonSafely: jest.fn(async () => undefined),
  };
});

jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
    warning: jest.fn(),
    info: jest.fn(),
    success: jest.fn(),
  },
}));

import i18n from '@/locales/config';
import { toast } from 'sonner';

import { resetRetrievalNoticeDedup } from '@/utils/retrieval-health-notice';
import { runChatCompletionStream } from '../run-stream';

const { __holder: chunkHolder } = jest.requireMock(
  '@/services/chat-completion-stream',
);

const warningToast = toast.warning as jest.Mock;
const errorToast = toast.error as jest.Mock;

const terminalFrameWith = (retrievalHealth: unknown) => [
  { answer: '见表 ', reference: {} },
  { answer: '外径 6.60mm。', reference: {} },
  {
    answer: '',
    reference: { chunks: [], doc_aggs: [], total: 1, retrieval_health: retrievalHealth },
    final: true,
  },
];

const health = (overrides: Record<string, unknown> = {}) => ({
  overall: 'degraded',
  evidence_completeness: 'partial',
  degradation_reason: null,
  ...overrides,
});

const run = () =>
  runChatCompletionStream({ conversationId: 'conv-1', messages: [] });

const toastTexts = () =>
  [...warningToast.mock.calls, ...errorToast.mock.calls].map(([text]) => text);

beforeEach(() => {
  jest.clearAllMocks();
  resetRetrievalNoticeDedup();
  chunkHolder.chunks = [];
  jest.spyOn(Date, 'now').mockReturnValue(5_000_000);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('C1-C6 through the deployed chat stream path', () => {
  it('C1: a full retrieval shows the user nothing at all', async () => {
    chunkHolder.chunks = terminalFrameWith(health({ overall: 'full' }));

    await run();

    expect(warningToast).not.toHaveBeenCalled();
    expect(errorToast).not.toHaveBeenCalled();
  });

  it('C2: an answer without a health signal shows the user nothing', async () => {
    chunkHolder.chunks = [
      { answer: '见表 ', reference: {} },
      { answer: '', reference: { chunks: [], doc_aggs: [], total: 0 }, final: true },
    ];

    await run();

    expect(warningToast).not.toHaveBeenCalled();
    expect(errorToast).not.toHaveBeenCalled();
  });

  it('C3: quota exhaustion discloses the honest degraded notice exactly once', async () => {
    chunkHolder.chunks = terminalFrameWith(
      health({
        overall: 'degraded',
        degradation_reason: 'EMBEDDING_QUOTA_EXHAUSTED',
        evidence_completeness: 'partial',
      }),
    );

    await run();

    expect(warningToast).toHaveBeenCalledTimes(1);
    expect(toastTexts()).toEqual([i18n.t('message.retrievalNotice.degraded')]);
    expect(errorToast).not.toHaveBeenCalled();
  });

  it('C5: another degradation discloses the same honest notice once', async () => {
    chunkHolder.chunks = terminalFrameWith(
      health({ overall: 'degraded', degradation_reason: 'STORE_UNAVAILABLE' }),
    );

    await run();

    expect(warningToast).toHaveBeenCalledTimes(1);
    expect(toastTexts()).toEqual([i18n.t('message.retrievalNotice.degraded')]);
  });

  it('C6: a failed retrieval discloses the explicit failure notice once', async () => {
    chunkHolder.chunks = terminalFrameWith(
      health({ overall: 'failed', degradation_reason: 'STORE_UNAVAILABLE' }),
    );

    await run();

    expect(errorToast).toHaveBeenCalledTimes(1);
    expect(toastTexts()).toEqual([i18n.t('message.retrievalNotice.failed')]);
    expect(warningToast).not.toHaveBeenCalled();
  });

  it('the answer is still rendered while the notice is shown', async () => {
    const { __store: mockStore } = jest.requireMock('../store');
    chunkHolder.chunks = terminalFrameWith(
      health({ overall: 'degraded', degradation_reason: 'EMBEDDING_QUOTA_EXHAUSTED' }),
    );

    await run();

    const calls = mockStore.applyAnswer.mock.calls;
    expect(calls[calls.length - 1][1].answer).toBe('见表 外径 6.60mm。');
  });

  it('D1: a degraded retrieval never stacks a second notice, however often the terminal frame is handled', async () => {
    chunkHolder.chunks = terminalFrameWith(
      health({ overall: 'degraded', degradation_reason: 'EMBEDDING_QUOTA_EXHAUSTED' }),
    );

    await run();
    // a second answer inside the same cooldown window, e.g. a rapid follow-up turn
    await run();

    expect(warningToast).toHaveBeenCalledTimes(1);
  });

  it('S1: no provider payload, credential or stack trace can reach the screen', async () => {
    const hostile = 'AQ.Ab8RN6LEAK api_key=secret Traceback: RESOURCE_EXHAUSTED';
    chunkHolder.chunks = terminalFrameWith(
      health({
        overall: 'degraded',
        degradation_reason: hostile,
        evidence_completeness: 'partial',
        provider_error: hostile,
      }),
    );

    await run();

    const rendered = JSON.stringify(toastTexts());
    for (const marker of ['AQ.Ab8RN6', 'api_key', 'Traceback', 'RESOURCE_EXHAUSTED']) {
      expect(rendered).not.toContain(marker);
    }
    expect(toastTexts()).toEqual([i18n.t('message.retrievalNotice.degraded')]);
  });
});

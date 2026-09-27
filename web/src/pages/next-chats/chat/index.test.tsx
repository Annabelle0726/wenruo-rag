import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useChatUrlParams } from '../hooks/use-chat-url';
import Chat from './index';

/**
 * Datasets the knowledge lookup resolves ids against. `kb-gone` is deliberately
 * absent: it stands for a dataset deleted after it was bound.
 */
const MockDatasets = [
  { id: 'kb-1', name: '国标知识库' },
  { id: 'kb-2', name: '电缆工艺库' },
  { id: 'kb-3', name: '试验报告库' },
];

const mockCreateSession = jest.fn();
const mockUpdateSession = jest.fn();
const mockUpdateChat = jest.fn();
const mockFetchSessionManually = jest.fn();
const mockSetSearchString = jest.fn();

/** The assistant's conversations, as its session list query would return them. */
let mockSessionList: Array<{
  id: string;
  name: string;
}> = [];

/** The assistant record: the datasets the chat is bound to. */
let mockAssistant: Record<string, any> = {};

/**
 * The assistant the drawer reads and writes.
 *
 * A whole record rather than a `dataset_ids` field alone: the drawer seeds its
 * form from this record with `reset`, and a required field the record does not
 * carry comes back undefined — the form's own schema would then reject the
 * submit under test before any request was made.
 */
function buildAssistant(datasetIds: string[] = []) {
  return {
    id: 'assistant-1',
    name: '电线助手',
    // Required by the drawer's schema, and carried by every real record.
    icon: '',
    llm_id: 'model-1',
    llm_setting: {},
    dataset_ids: datasetIds,
    similarity_threshold: 0.25,
    vector_similarity_weight: 0.3,
    rerank_candidates_count: 64,
    meta_data_filter: { method: 'disabled', manual: [] },
    prompt_config: {
      quote: true,
      keyword: false,
      tts: false,
      refine_multiturn: true,
      system: 'Answer from {knowledge}',
    },
  };
}

// The chat hooks reach the app router at module scope, which builds a browser
// router jsdom cannot host; the layouts are the app shell this page renders
// inside. Both are stubbed at their boundary, so this suite covers the page's
// own wiring: which drawer it raises, what the drawer saves, and what it hands
// the header.
jest.mock('@/routes', () => ({ Routes: { Chat: '/chat' } }));

jest.mock('@/layouts/root-layout', () => ({
  // Typed `any` on purpose: a jest.mock factory is transformed by Babel, which
  // cannot strip a type annotation that names an imported binding.
  RootLayoutContainer: ({ children }: any) => <div>{children}</div>,
}));

jest.mock('@/layouts/components/breadcrumb-context', () => ({
  BreadcrumbTrail: () => null,
}));

jest.mock('@/hooks/use-chat-request', () => {
  const { useSearchParams } = require('react-router');
  const { ChatSearchParams } = require('@/constants/chat');

  return {
    ChatApiAction: { FetchSessionList: 'fetchSessionList' },
    useGetChatSearchParams: () => {
      const [searchParams] = useSearchParams();

      return {
        dialogId: searchParams.get(ChatSearchParams.DialogId) || '',
        conversationId: searchParams.get(ChatSearchParams.ConversationId) || '',
        isNew: searchParams.get(ChatSearchParams.isNew) || '',
      };
    },
    useFetchChat: () => ({ data: mockAssistant, loading: false }),
    useFetchChatList: () => ({ data: { chats: [] } }),
    useFetchSessionList: () => ({
      data: mockSessionList,
      loading: false,
      searchString: '',
      setSearchString: mockSetSearchString,
      handleInputChange: jest.fn(),
    }),
    useFetchSessionManually: () => ({
      fetchSessionManually: mockFetchSessionManually,
      loading: false,
    }),
    usePatchChat: () => ({ patchChat: jest.fn(), loading: false }),
    useUpdateChat: () => ({ updateChat: mockUpdateChat, loading: false }),
    useCreateSession: () => ({
      createSession: mockCreateSession,
      loading: false,
    }),
    useUpdateSession: () => ({
      updateSession: mockUpdateSession,
      loading: false,
    }),
  };
});

jest.mock('@/hooks/use-knowledge-request', () => ({
  useFetchDatasetsByIds: (ids: string[]) => ({
    data: MockDatasets.filter((dataset) => ids.includes(dataset.id)),
    loading: false,
  }),
  // The prologue section's metadata filter asks for these; no dataset in this
  // suite carries any.
  useFetchKnowledgeMetadataKeys: () => ({ data: [], loading: false }),
  // Reported as settled with nothing stale, so the dataset field's staleness
  // rule never contributes to whether the form below submits.
  useStaleDatasetIds: () => ({
    staleDatasetIds: new Set<string>(),
    settled: true,
  }),
}));

jest.mock('@/hooks/use-llm-request', () => ({
  useFindLlmByUuid: () => () => undefined,
}));

// Only reached through the drawer's model section, and it fetches the tenant's
// model list from there. `forwardRef` because the field it sits in hands it a
// ref, which a plain function component cannot take.
jest.mock('@/components/model-tree-select', () => ({
  ModelTreeSelect: require('react').forwardRef(() => null),
}));

/**
 * Stands in for the shared selector the drawer must use: it reports the
 * `dataset_ids` the form was seeded with — the pre-selection the drawer has to
 * perform — and can add one, so the save path runs without the popover's
 * internals.
 */
jest.mock('@/components/knowledge-base-item', () => {
  const { useFormContext, useWatch } = require('react-hook-form');

  return {
    KnowledgeBaseFormField: () => {
      const form = useFormContext();
      const selected = (useWatch({
        control: form.control,
        name: 'dataset_ids',
      }) ?? []) as string[];

      return (
        <div
          data-testid="shared-dataset-selector"
          data-selected={selected.join(',')}
        >
          {MockDatasets.map((dataset) => (
            <button
              key={dataset.id}
              type="button"
              data-testid={`pick-${dataset.id}`}
              onClick={() =>
                form.setValue('dataset_ids', [...selected, dataset.id])
              }
            >
              {dataset.name}
            </button>
          ))}
        </div>
      );
    },
  };
});

// The rail is covered by its own suite: it is stubbed here for the three
// controls this page owns the answer to.
jest.mock('./sessions', () => ({
  Sessions: ({
    onNewConversation,
    onOpenSettings,
    onVisibleChange,
  }: {
    onNewConversation: () => void;
    onOpenSettings: () => void;
    onVisibleChange: (visible: boolean) => void;
  }) => (
    <div data-testid="sessions-rail">
      <button
        type="button"
        data-testid="rail-new-conversation"
        onClick={onNewConversation}
      >
        new
      </button>
      <button
        type="button"
        data-testid="rail-settings"
        onClick={onOpenSettings}
      >
        settings
      </button>
      <button
        type="button"
        data-testid="rail-collapse"
        onClick={() => onVisibleChange(false)}
      >
        collapse
      </button>
    </div>
  ),
}));

jest.mock('./chat-box/single-chat-box', () => ({
  SingleChatBox: ({ loading }: { loading?: boolean }) => (
    <div data-testid="chat-box" data-loading={String(Boolean(loading))} />
  ),
}));

// Only reached by the multi-model view, which is off in this suite; it also
// drags the message input in, and with it a voice-recorder package that is not
// installed.
jest.mock('./chat-box/next-multiple-chat-box', () => ({
  MultipleChatBox: () => null,
}));

jest.mock('../hooks/use-summarize-conversation-title', () => ({
  useSummarizeConversationTitle: () => ({ summarizing: false }),
}));

/** Reports the conversation the page has open, so a test can read the route. */
function RouteParamsProbe() {
  const [searchParams] = useSearchParams();

  return (
    <div data-testid="route-params">
      {`${searchParams.get('conversationId') ?? ''}|${searchParams.get('isNew') ?? ''}`}
    </div>
  );
}

/**
 * Replaces the route the way the first send does — the placeholder the rail
 * seeded becomes the session the server just created — without running the
 * completion behind it, which is another suite's subject.
 */
function FirstSendProbe({ sessionId }: { sessionId: string }) {
  const { setConversationBoth } = useChatUrlParams();

  return (
    <button
      type="button"
      data-testid="first-send"
      onClick={() => setConversationBoth(sessionId, '')}
    >
      send
    </button>
  );
}

function renderChatPage(route: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      {/* The page normally sits inside the app shell's `TooltipProvider`, which
          the stubbed layout above does not render — and the drawer's form fields
          carry tooltips. */}
      <TooltipProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route
              path="/chat/:id"
              element={
                <>
                  <RouteParamsProbe />
                  <FirstSendProbe sessionId="server-9" />
                  <Chat />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

/** The one settings drawer — the panel the gear opens, and the only dataset UI. */
const settingsDrawer = () => screen.queryByTestId('chat-detail-settings');
const selectedDatasetIds = () =>
  screen.getByTestId('shared-dataset-selector').dataset.selected;

const submitSettings = () =>
  fireEvent.submit(
    screen.getByTestId('shared-dataset-selector').closest('form')!,
  );

/**
 * Opens the model & dataset section, which is where the dataset field lives:
 * the drawer only opens it by itself when there is nothing selected yet, and
 * reveals the retrieval settings first whenever there is.
 */
const openDatasetFieldSection = () =>
  fireEvent.click(screen.getByTestId('chat-settings-section-model'));

/** Waits for the open conversation's own read, which the page loads behind. */
const waitForOpenSession = () =>
  waitFor(() =>
    expect(screen.getByTestId('chat-box')).toHaveAttribute(
      'data-loading',
      'false',
    ),
  );

// jsdom lays nothing out, and an invalid submit scrolls the first error into
// view; without this the reveal throws instead of being observable.
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

beforeEach(() => {
  jest.clearAllMocks();
  mockSessionList = [];
  mockAssistant = buildAssistant();
  mockFetchSessionManually.mockResolvedValue({ id: 'server-1', messages: [] });
});

describe('a chat with nothing to retrieve from', () => {
  it('raises the settings drawer, prompting for the datasets a chat needs', () => {
    renderChatPage('/chat/assistant-1');

    expect(settingsDrawer()).toBeInTheDocument();
    // The prompt is in the same panel, not in a drawer of its own.
    expect(screen.getByTestId('chat-settings-no-dataset')).toHaveTextContent(
      'No dataset is selected',
    );
    // And the field that answers it is the section that comes up, not the
    // retrieval settings.
    expect(screen.getByTestId('chat-settings-section-model')).toHaveAttribute(
      'data-state',
      'open',
    );
    expect(
      screen.getByTestId('chat-settings-section-retrieval'),
    ).toHaveAttribute('data-state', 'closed');
  });

  it('stops prompting once a dataset is picked', () => {
    renderChatPage('/chat/assistant-1');

    fireEvent.click(screen.getByTestId('pick-kb-1'));

    expect(screen.queryByTestId('chat-settings-no-dataset')).toBeNull();
  });

  it('leaves a bound chat alone, and names its datasets in the header', async () => {
    mockAssistant = buildAssistant(['kb-1']);
    mockSessionList = [{ id: 'server-1', name: '国标查询' }];

    renderChatPage('/chat/assistant-1?conversationId=server-1');
    await waitForOpenSession();

    // Every conversation under this chat answers from its datasets, so there is
    // nothing to ask the user about — not here and not in the drawer either.
    expect(settingsDrawer()).toBeNull();

    fireEvent.click(screen.getByTestId('rail-collapse'));

    const tags = await screen.findByTestId('chat-detail-dataset-tags');

    expect(tags).toHaveTextContent('国标知识库');
    expect(settingsDrawer()).toBeNull();
  });

  it('leaves a conversation under a chat with datasets alone', async () => {
    mockAssistant = buildAssistant(['kb-1', 'kb-3']);
    mockSessionList = [{ id: 'server-1', name: '国标查询' }];

    renderChatPage('/chat/assistant-1?conversationId=server-1');
    await waitForOpenSession();

    fireEvent.click(screen.getByTestId('rail-collapse'));

    expect(
      await screen.findByTestId('chat-detail-dataset-tags'),
    ).toHaveTextContent('试验报告库');
    expect(settingsDrawer()).toBeNull();
  });

  it('raises it once: a close is not argued with, and no session is written', async () => {
    mockSessionList = [{ id: 'server-1', name: '国标查询' }];

    renderChatPage('/chat/assistant-1?conversationId=server-1');
    await waitFor(() => expect(settingsDrawer()).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('chat-detail-settings-cancel'));
    await waitFor(() => expect(settingsDrawer()).toBeNull());

    // Closing the panel decides nothing about the conversation, so nothing is
    // created or rebound by it — and the page re-rendering around the close
    // does not put the panel back over the user.
    expect(mockCreateSession).not.toHaveBeenCalled();
    expect(mockUpdateSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('rail-collapse'));

    expect(settingsDrawer()).toBeNull();
  });

  it('does not raise it again once the first send turns the placeholder into a session', async () => {
    renderChatPage(
      '/chat/assistant-1?conversationId=temp-placeholder&isNew=true',
    );

    await waitFor(() => expect(settingsDrawer()).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('chat-detail-settings-cancel'));
    await waitFor(() => expect(settingsDrawer()).toBeNull());

    fireEvent.click(screen.getByTestId('first-send'));

    await waitFor(() =>
      expect(screen.getByTestId('route-params')).toHaveTextContent('server-9|'),
    );
    // The placeholder and the session created from it are one conversation to
    // the user: the panel they dismissed must not come back over the answer they
    // just asked for.
    expect(settingsDrawer()).toBeNull();
  });

  it('does not raise it again once a first question creates the session', async () => {
    renderChatPage('/chat/assistant-1');

    await waitFor(() => expect(settingsDrawer()).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('chat-detail-settings-cancel'));
    await waitFor(() => expect(settingsDrawer()).toBeNull());

    fireEvent.click(screen.getByTestId('first-send'));

    await waitFor(() =>
      expect(screen.getByTestId('route-params')).toHaveTextContent('server-9|'),
    );
    // Same conversation, same close: a session that was not even open when the
    // panel was raised is not a reason to raise it again.
    expect(settingsDrawer()).toBeNull();
  });
});

describe("a chat's datasets in the settings drawer", () => {
  it('opens from a tag, pre-selected on the datasets the chat is bound to', async () => {
    mockAssistant = buildAssistant(['kb-1', 'kb-2']);
    mockSessionList = [{ id: 'server-1', name: '国标查询' }];

    renderChatPage('/chat/assistant-1?conversationId=server-1');
    await waitForOpenSession();
    fireEvent.click(screen.getByTestId('rail-collapse'));
    await screen.findByTestId('chat-detail-dataset-tags');

    expect(settingsDrawer()).toBeNull();
    fireEvent.click(screen.getByText('电缆工艺库'));

    // The same panel the gear opens, opened on the chat's own set: the header
    // tag that was clicked names one of them.
    expect(settingsDrawer()).toBeInTheDocument();
    // A chat that HAS datasets is never told it has selected none.
    expect(screen.queryByTestId('chat-settings-no-dataset')).toBeNull();
    expect(
      screen.getByTestId('chat-settings-section-retrieval'),
    ).toHaveAttribute('data-state', 'open');

    openDatasetFieldSection();

    expect(selectedDatasetIds()).toBe('kb-1,kb-2');
  });

  it("writes the chat's datasets when the selection changes", async () => {
    mockAssistant = buildAssistant(['kb-1']);
    mockSessionList = [{ id: 'server-1', name: '国标查询' }];

    renderChatPage('/chat/assistant-1?conversationId=server-1');
    await waitForOpenSession();

    fireEvent.click(screen.getByTestId('rail-settings'));
    openDatasetFieldSection();

    expect(selectedDatasetIds()).toBe('kb-1');

    fireEvent.click(screen.getByTestId('pick-kb-3'));
    submitSettings();

    await waitFor(() => expect(mockUpdateChat).toHaveBeenCalledTimes(1));
    // The field is part of the chat's own settings: what it saves is the set
    // every conversation under this chat answers from.
    expect(mockUpdateChat.mock.calls[0][0].params.dataset_ids).toEqual([
      'kb-1',
      'kb-3',
    ]);
    // And nothing is bound to the conversation: it has no dataset set of its own
    // to be mixed up.
    expect(mockUpdateSession).not.toHaveBeenCalled();
    expect(mockCreateSession).not.toHaveBeenCalled();
  });

  it('saves the set the panel opened on, without a session binding', async () => {
    mockAssistant = buildAssistant(['kb-1', 'kb-2']);
    mockSessionList = [{ id: 'server-1', name: '国标查询' }];

    renderChatPage('/chat/assistant-1?conversationId=server-1');
    await waitForOpenSession();

    fireEvent.click(screen.getByTestId('rail-settings'));
    openDatasetFieldSection();

    expect(selectedDatasetIds()).toBe('kb-1,kb-2');
    submitSettings();

    await waitFor(() => expect(mockUpdateChat).toHaveBeenCalledTimes(1));
    expect(mockUpdateChat.mock.calls[0][0].params.dataset_ids).toEqual([
      'kb-1',
      'kb-2',
    ]);
    expect(mockUpdateSession).not.toHaveBeenCalled();
  });

  it('saves the chosen datasets for a conversation the server does not know yet', async () => {
    mockCreateSession.mockResolvedValue({ code: 0, data: { id: 'server-9' } });

    renderChatPage(
      '/chat/assistant-1?conversationId=temp-placeholder&isNew=true',
    );
    await waitFor(() => expect(settingsDrawer()).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('pick-kb-2'));
    submitSettings();

    await waitFor(() => expect(mockUpdateChat).toHaveBeenCalledTimes(1));
    // The choice is the CHAT's, so a conversation that only exists in the
    // browser needs no row of its own to answer from it — and the save does not
    // create one behind the user.
    expect(mockUpdateChat.mock.calls[0][0].params.dataset_ids).toEqual(['kb-2']);
    expect(mockCreateSession).not.toHaveBeenCalled();
    expect(screen.getByTestId('route-params')).toHaveTextContent(
      'temp-placeholder|true',
    );
  });

  it("saves the chat's other settings with the same request", async () => {
    mockAssistant = buildAssistant(['kb-1']);
    mockSessionList = [{ id: 'server-1', name: '国标查询' }];

    renderChatPage('/chat/assistant-1?conversationId=server-1');
    await waitForOpenSession();

    fireEvent.click(screen.getByTestId('rail-settings'));
    openDatasetFieldSection();
    fireEvent.click(screen.getByTestId('pick-kb-2'));
    submitSettings();

    await waitFor(() => expect(mockUpdateChat).toHaveBeenCalledTimes(1));

    // One panel, one record: the datasets travel with the name and the prompt
    // settings rather than in a second request of their own.
    const params = mockUpdateChat.mock.calls[0][0].params;

    expect(params.dataset_ids).toEqual(['kb-1', 'kb-2']);
    expect(params.name).toBe('电线助手');
    expect(mockUpdateSession).not.toHaveBeenCalled();
  });
});

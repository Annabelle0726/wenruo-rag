import { render, screen } from '@testing-library/react';

import { LlmWikiView } from '../llm-wiki-view';
import { WikiDetailContent } from '../wiki-detail-content';
import { WikiNavBar } from '../wiki-left-panel/wiki-nav-bar';

// The three reads under test, held in `mock*`-named objects because a jest.mock
// factory may only close over names it is allowed to see.
const mockTopicsState = {
  topics: [] as { topic: string; title: string; slug: string }[],
  loading: false,
  error: undefined as Error | undefined,
  refetch: jest.fn(),
};

const mockArtifactsState = {
  artifacts: [] as { slug: string; title: string }[],
  loading: false,
  error: undefined as Error | undefined,
  refetch: jest.fn(),
};

const mockDetailState = {
  error: undefined as Error | undefined,
  refetch: jest.fn(),
};

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  // `@/locales/config` is reached through the app's request layer and calls
  // `i18n.use(initReactI18next)`; without it the whole import chain throws.
  initReactI18next: { type: '3rdParty', init: () => undefined },
}));

jest.mock('react-router', () => ({
  useParams: () => ({ id: 'kb-1' }),
}));

jest.mock('@/utils/backend-variant', () => ({
  useIsGoBackend: () => false,
}));

// The view invalidates these keys when a compilation run ends; this suite renders
// it without a cache, and the keys are stubbed with it.
jest.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: jest.fn() }),
}));

// The header and the toolbar decorate their controls with tooltips, which need a
// provider this suite has no reason to render: the controls themselves are what
// the assertions look at.
jest.mock('@/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  TooltipContent: () => null,
  TooltipTrigger: ({ children }: { children?: React.ReactNode }) => (
    <>{children}</>
  ),
  TooltipProvider: ({ children }: { children?: React.ReactNode }) => (
    <>{children}</>
  ),
}));

jest.mock('@/hooks/use-dataset-generate', () => ({
  GenerateType: { Artifact: 'artifact' },
  useGenerateStatus: () => ({ status: 'idle', percent: 0 }),
  useTraceRunData: () => ({ data: undefined }),
  useDatasetGenerate: () => ({
    runGenerate: jest.fn(),
    pauseGenerate: jest.fn(),
  }),
}));

jest.mock('@/hooks/use-knowledge-request', () => ({
  useFetchArtifactTopicList: () => mockTopicsState,
  useFetchArtifactList: () => mockArtifactsState,
  useFetchKnowledgeBaseConfiguration: () => ({
    data: { chunk_count: 0, pipeline_id: '' },
  }),
  useKnowledgeBaseId: () => 'kb-1',
  // The header, the toolbar and the sheets around the pane reach for these on
  // mount; none of them is what this suite is about.
  useFetchWikiCommits: () => ({ commits: [], loading: false }),
  useFetchWikiCommit: () => ({ data: undefined, loading: false }),
  useFetchArtifactPage: () => ({
    data: undefined,
    loading: false,
    error: undefined,
    refetch: jest.fn(),
  }),
  useFetchArtifactAlteration: () => ({ data: undefined, loading: false }),
  useFetchArtifactGraph: () => ({ data: undefined, loading: false }),
  useRunArtifactIndex: () => ({ run: jest.fn(), loading: false }),
  useUpdateArtifactPage: () => ({
    mutateAsync: jest.fn(),
    isPending: false,
    data: undefined,
  }),
  useClearWiki: () => ({ mutateAsync: jest.fn(), isPending: false }),
  ArtifactAlterationKeys: { detail: () => ['artifact-alteration'] },
  ArtifactKeys: {
    listByDataset: () => ['artifacts'],
    detail: () => ['artifact-detail'],
  },
  ArtifactTopicKeys: {
    listByDataset: () => ['artifact-topics'],
    list: () => ['artifact-topics'],
  },
}));

// The editor panel is the thing that made a failed read look like an empty page,
// and it drags the whole markdown pipeline in behind it: what matters here is
// only whether the pane rendered it.
jest.mock('../wiki-detail-editor-panel', () => ({
  WikiDetailEditorPanel: () => <div data-testid="wiki-detail-editor-panel" />,
}));

// react-resizable-panels ships ESM that this suite's runner does not transform,
// and the panes are not what is under test: their children are.
jest.mock('@/components/ui/resizable', () => ({
  ResizableHandle: () => null,
  ResizablePanel: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
  ResizablePanelGroup: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

// The graph panel is only reachable through the left panel's Graph tab, but it
// is imported eagerly and react-force-graph-2d is ESM the runner cannot load.
jest.mock('@/components/artifact-force-graph', () => ({
  __esModule: true,
  ArtifactForceGraph: () => null,
  default: () => null,
}));

jest.mock('../hooks/use-run-end-effect', () => ({
  useRunEndEffect: () => undefined,
}));

jest.mock('../hooks/use-compilation-artifact', () => ({
  useCompilationArtifact: () => ({
    selectedArtifact: null,
    selectedVersion: null,
    selectVersion: jest.fn(),
    handleSelectArtifact: jest.fn(),
    clearSelectedArtifact: jest.fn(),
  }),
}));

jest.mock('../wiki-left-panel/hooks/use-wiki-navigation', () => ({
  useWikiNavigation: () => ({
    scrollRef: { current: null },
    searchString: '',
    selectedTopic: null,
    selectedTopicPath: '产品',
    visibleTopics: [],
    showArtifacts: true,
    artifacts: mockArtifactsState.artifacts,
    artifactError: mockArtifactsState.error,
    reloadArtifacts: mockArtifactsState.refetch,
    loading: mockArtifactsState.loading,
    hasMore: false,
    handleSearchChange: jest.fn(),
    handleSelectTopic: jest.fn(),
    handleSelectTopicPath: jest.fn(),
    handleBackToTopics: jest.fn(),
    handleScroll: jest.fn(),
  }),
}));

jest.mock('../hooks/use-wiki-detail-content', () => ({
  useWikiDetailContent: () => ({
    isVersionView: false,
    title: '产品概览',
    displayedArtifact: { slug: 'overview', title: '产品概览' },
    displayedContent: '',
    displayedPageType: 'wiki',
    displayedSlug: 'overview',
    selectedArtifact: { slug: 'overview', title: '产品概览' },
    selectedVersion: null,
    commitDetail: null,
    canGoBack: false,
    previousEntry: null,
    previousEntryTitle: undefined,
    linkNavLoading: false,
    loading: false,
    pageError: mockDetailState.error,
    reloadPage: mockDetailState.refetch,
    editedContent: '',
    isDirty: false,
    referenceDocuments: [],
    isOpen: false,
    open: jest.fn(),
    setIsOpen: jest.fn(),
    form: undefined,
    handleConfirm: jest.fn(),
    isUpdating: false,
    handleCancelEdit: jest.fn(),
    handleContentChange: jest.fn(),
    handleMarkdownLinkClick: jest.fn(),
    handleBack: jest.fn(),
    handleExport: jest.fn(),
    onSelectVersion: jest.fn(),
  }),
}));

const artifact = { slug: 'overview', title: '产品概览', page_type: 'wiki' };
const READ_FAILED = 'knowledgeCompilation.readFailedTitle';

beforeEach(() => {
  mockTopicsState.topics = [];
  mockTopicsState.loading = false;
  mockTopicsState.error = undefined;
  mockTopicsState.refetch = jest.fn();
  mockArtifactsState.artifacts = [];
  mockArtifactsState.loading = false;
  mockArtifactsState.error = undefined;
  mockArtifactsState.refetch = jest.fn();
  mockDetailState.error = undefined;
  mockDetailState.refetch = jest.fn();
});

describe('knowledge compilation read failures', () => {
  it('shows the failure panel, not the empty state, when the topic read failed', () => {
    mockTopicsState.error = new Error(
      'knowledge compilation store unavailable',
    );

    render(<LlmWikiView />);

    expect(screen.getByTestId('compilation-read-failure')).toBeInTheDocument();
    expect(screen.getByText(READ_FAILED)).toBeInTheDocument();
    // The empty state's own copy and its action must not be on screen: "nothing
    // here yet" is not a claim a failed read is entitled to make, and its
    // generate button would invite work against a store that cannot be read.
    expect(
      screen.queryByText('knowledgeCompilation.noWikiPages'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText('knowledgeCompilation.generate'),
    ).not.toBeInTheDocument();
  });

  it('still shows the empty state when the read succeeded with no topics', () => {
    render(<LlmWikiView />);

    expect(
      screen.getByText('knowledgeCompilation.noWikiPages'),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('compilation-read-failure'),
    ).not.toBeInTheDocument();
  });

  it('lets the reader ask again from the failure panel', () => {
    const refetch = jest.fn();
    mockTopicsState.error = new Error(
      'knowledge compilation store unavailable',
    );
    mockTopicsState.refetch = refetch;

    render(<LlmWikiView />);
    screen.getByRole('button', { name: 'common.retry' }).click();

    expect(refetch).toHaveBeenCalled();
  });

  it('separates a failed artifact list from an empty one', () => {
    mockArtifactsState.error = new Error(
      'knowledge compilation store unavailable',
    );

    render(<WikiNavBar selectedArtifact={null} onSelectArtifact={jest.fn()} />);

    expect(screen.getByTestId('compilation-read-failure')).toBeInTheDocument();
  });

  it('shows no failure panel when the artifact list loaded', () => {
    render(<WikiNavBar selectedArtifact={null} onSelectArtifact={jest.fn()} />);

    expect(
      screen.queryByTestId('compilation-read-failure'),
    ).not.toBeInTheDocument();
  });

  it('does not render the editor over a page whose read failed', () => {
    mockDetailState.error = new Error(
      'knowledge compilation store unavailable',
    );

    render(
      <WikiDetailContent
        selectedArtifact={artifact}
        selectedVersion={null}
        onSelectVersion={jest.fn()}
        onSelectArtifact={jest.fn()}
      />,
    );

    expect(screen.getByTestId('compilation-read-failure')).toBeInTheDocument();
    expect(
      screen.queryByTestId('wiki-detail-editor-panel'),
    ).not.toBeInTheDocument();
  });

  it('keeps the editor when the page read succeeded', () => {
    render(
      <WikiDetailContent
        selectedArtifact={artifact}
        selectedVersion={null}
        onSelectVersion={jest.fn()}
        onSelectArtifact={jest.fn()}
      />,
    );

    expect(screen.getByTestId('wiki-detail-editor-panel')).toBeInTheDocument();
    expect(
      screen.queryByTestId('compilation-read-failure'),
    ).not.toBeInTheDocument();
  });
});

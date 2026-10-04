import i18n from '@/locales/config';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import Agents from './index';

const mockShowCreatingModal = jest.fn();
const mockImportJson = jest.fn();

jest.mock('@/hooks/use-user-setting-request', () => ({
  useFetchTenantInfo: () => ({ data: { role: 'owner' } }),
}));

// The route table builds a browser router on import, which jsdom cannot host;
// only the paths this page links to are needed here.
jest.mock('@/routes', () => ({
  Routes: {
    AgentTemplates: '/agent-templates',
    CompilationTemplatesEditNext: '/compilation-templates/edit',
  },
}));

jest.mock('@/hooks/use-agent-request', () => ({
  useFetchAgentListByPage: () => ({
    data: [],
    loading: false,
    pagination: { current: 1, pageSize: 12, total: 0 },
    setPagination: jest.fn(),
    searchString: '',
    setSearchString: jest.fn(),
    handleInputChange: jest.fn(),
    filterValue: {},
    setFilterValue: jest.fn(),
    handleFilterSubmit: jest.fn(),
    checkValue: jest.fn(),
  }),
}));

jest.mock('@/hooks/use-compilation-template-group-request', () => ({
  useDeleteCompilationTemplateGroup: () => ({ deleteGroup: jest.fn() }),
}));

jest.mock('./hooks/use-create-agent', () => ({
  useCreateAgentOrPipeline: () => ({
    creatingVisible: false,
    hideCreatingModal: jest.fn(),
    showCreatingModal: () => mockShowCreatingModal(),
    loading: false,
    handleCreateAgentOrPipeline: jest.fn(),
  }),
}));

jest.mock('./hooks/use-select-filters', () => ({
  useSelectFilters: () => [],
}));

jest.mock('./use-import-json', () => ({
  useHandleImportJsonFile: () => ({
    fileUploadVisible: false,
    handleImportJson: () => mockImportJson(),
    hideFileUploadModal: jest.fn(),
    onFileUploadOk: jest.fn(),
  }),
}));

jest.mock('./use-rename-agent', () => ({
  useRenameAgent: () => ({
    agentRenameLoading: false,
    initialAgentName: '',
    onAgentRenameOk: jest.fn(),
    agentRenameVisible: false,
    hideAgentRenameModal: jest.fn(),
    showAgentRenameModal: jest.fn(),
  }),
}));

const renderAgents = () =>
  render(
    <MemoryRouter>
      <Agents />
    </MemoryRouter>,
  );

// The page offers three ways to create an agent and exactly one place to pick
// between them: the toolbar menu. The empty state is the standard create tile,
// not a second, dashed copy of the same options.
const createOptionLabels = () => [
  i18n.t('flow.createFromBlank'),
  i18n.t('flow.createFromTemplate'),
  i18n.t('flow.importJsonFile'),
];

const expectCreateOptionsAbsent = () => {
  createOptionLabels().forEach((label) => {
    expect(screen.queryByText(label)).toBeNull();
  });
};

describe('agents page create entry', () => {
  beforeEach(() => {
    mockShowCreatingModal.mockClear();
    mockImportJson.mockClear();
  });

  it('stands the standard empty card in for the list', () => {
    renderAgents();

    const tile = screen.getByTestId('agents-empty-create');

    expect(tile).toHaveTextContent(i18n.t('empty.agentTitle'));
    // The shared SvgIcon paints the agent asset as an <img>; the tile carries no
    // emoji and no icon of its own.
    expect(tile.querySelector('img')).not.toBeNull();
    expectCreateOptionsAbsent();
  });

  it('opens the toolbar menu from the empty card', async () => {
    renderAgents();

    fireEvent.click(screen.getByTestId('agents-empty-create'));

    const menu = await screen.findByTestId('agent-create-menu');

    expect(screen.getAllByTestId('agent-create-menu')).toHaveLength(1);
    createOptionLabels().forEach((label) => {
      expect(within(menu).getAllByText(label)).toHaveLength(1);
    });
  });

  it('opens the same menu from the toolbar button', async () => {
    renderAgents();

    fireEvent.keyDown(screen.getByTestId('create-agent'), {
      key: 'ArrowDown',
    });

    const menu = await screen.findByTestId('agent-create-menu');

    expect(screen.getAllByTestId('agent-create-menu')).toHaveLength(1);
    createOptionLabels().forEach((label) => {
      expect(within(menu).getAllByText(label)).toHaveLength(1);
    });
  });

  it('creates from blank through the menu item', async () => {
    renderAgents();

    fireEvent.click(screen.getByTestId('agents-empty-create'));

    const menu = await screen.findByTestId('agent-create-menu');

    fireEvent.click(within(menu).getByText(i18n.t('flow.createFromBlank')));

    expect(mockShowCreatingModal).toHaveBeenCalledTimes(1);
  });

  it('imports a JSON file through the menu item', async () => {
    renderAgents();

    fireEvent.click(screen.getByTestId('agents-empty-create'));

    const menu = await screen.findByTestId('agent-create-menu');

    fireEvent.click(within(menu).getByText(i18n.t('flow.importJsonFile')));

    expect(mockImportJson).toHaveBeenCalledTimes(1);
  });
});

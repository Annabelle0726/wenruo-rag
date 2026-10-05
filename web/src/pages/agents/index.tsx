import { CardContainer } from '@/components/card-container';
import { CardGridPlaceholder } from '@/components/card-grid-placeholder';
import { EmptyCardType } from '@/components/empty/constant';
import { EmptyAppCard } from '@/components/empty/empty';
import ListFilterBar from '@/components/list-filter-bar';
import { RenameDialog } from '@/components/rename-dialog';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import { ListDeletionKey } from '@/constants/list-deletion';
import { useGoToPreviousPageOnEmpty } from '@/hooks/logic-hooks';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { useFetchAgentListByPage } from '@/hooks/use-agent-request';
import { useDeleteCompilationTemplateGroup } from '@/hooks/use-compilation-template-group-request';
import { useFetchTenantInfo } from '@/hooks/use-user-setting-request';
import { canManageTenant } from '@/utils/tenant-role';
import { Routes } from '@/routes';
import { pick } from 'lodash';
import { Clipboard, ClipboardPlus, FileInput, Plus } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router';
import { AgentCard } from './agent-card';
import { CompilationTemplateCard } from './compilation-template-card';
import { CreateAgentDialog } from './create-agent-dialog';
import { useCreateAgentOrPipeline } from './hooks/use-create-agent';
import { useSelectFilters } from './hooks/use-select-filters';
import { UploadAgentDialog } from './upload-agent-dialog';
import { useHandleImportJsonFile } from './use-import-json';
import { useRenameAgent } from './use-rename-agent';

const CompilationGroupCategory = 'compilation_template_group';

export default function Agents() {
  const { t } = useTranslation();

  const {
    data,
    loading: listLoading,
    pagination,
    setPagination,
    searchString,
    setSearchString,
    handleInputChange,
    filterValue,
    setFilterValue,
    handleFilterSubmit,
    checkValue,
  } = useFetchAgentListByPage();

  const { navigateToAgentTemplates } = useNavigatePage();
  const navigate = useNavigate();

  const {
    agentRenameLoading,
    initialAgentName,
    onAgentRenameOk,
    agentRenameVisible,
    hideAgentRenameModal,
    showAgentRenameModal,
  } = useRenameAgent();

  const {
    creatingVisible,
    hideCreatingModal,
    showCreatingModal,
    loading,
    handleCreateAgentOrPipeline,
  } = useCreateAgentOrPipeline();

  const {
    handleImportJson,
    fileUploadVisible,
    onFileUploadOk,
    hideFileUploadModal,
  } = useHandleImportJsonFile();

  const { deleteGroup } = useDeleteCompilationTemplateGroup();
  const { data: tenant } = useFetchTenantInfo();
  const canManageTemplates = canManageTenant(tenant.role);

  const filters = useSelectFilters();

  // The three ways to create an agent live in one menu, so the toolbar button and
  // the empty state's create tile open that same menu instead of each offering
  // their own copy of the options.
  const [createMenuOpen, setCreateMenuOpen] = useState(false);

  const handleOpenCreateMenu = useCallback(() => {
    setCreateMenuOpen(true);
  }, []);

  const handleCreateMenuOpenChange = useCallback((open: boolean) => {
    setCreateMenuOpen(open);
  }, []);

  useEffect(() => {
    checkValue(filters);
  }, [filters, checkValue]);

  const handlePageChange = useCallback(
    (page: number, pageSize?: number) => {
      setPagination({ page, pageSize });
    },
    [setPagination],
  );
  useGoToPreviousPageOnEmpty(data?.length, listLoading, {
    deletionKey: ListDeletionKey.AgentList,
    searchString,
    setSearchString,
    filterValue,
    setFilterValue,
  });

  const handleEditCompilation = useCallback(
    (id: string) => () => {
      navigate(`${Routes.CompilationTemplatesEditNext}/${id}?source=agents`);
    },
    [navigate],
  );

  const handleDeleteCompilation = useCallback(
    async (id: string) => {
      await deleteGroup(id);
    },
    [deleteGroup],
  );

  const [searchUrl, setSearchUrl] = useSearchParams();
  const isCreate = searchUrl.get('isCreate') === 'true';

  useEffect(() => {
    if (isCreate) {
      showCreatingModal();
      searchUrl.delete('isCreate');
      setSearchUrl(searchUrl);
    }
  }, [isCreate, showCreatingModal, searchUrl, setSearchUrl]);

  return (
    <>
      <article
        className="size-full min-w-0 flex flex-col"
        data-testid="agents-list"
      >
        <header className="page-gutter page-toolbar min-w-0">
          <ListFilterBar
            searchVariant="capsule"
            title={t('flow.agents')}
            icon="agents"
            searchString={searchString}
            onSearchChange={handleInputChange}
            filters={filters}
            onChange={handleFilterSubmit}
            value={filterValue}
          >
            <DropdownMenu
              open={createMenuOpen}
              onOpenChange={handleCreateMenuOpenChange}
            >
              <DropdownMenuTrigger data-testid="create-agent" asChild>
                {/* Primary action: the same 32px ceramic CTA every other list
                    toolbar carries, label included — an icon-only one beside
                    their labelled ones never lines up. */}
                <Button className="ceramic-cta h-8 rounded-[2px] px-3 text-xs font-medium gap-1.5">
                  <Plus className="size-3.5" />
                  {t('flow.createAgentApp')}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent data-testid="agent-create-menu">
                <DropdownMenuItem
                  justifyBetween={false}
                  onClick={showCreatingModal}
                >
                  <Clipboard />
                  {t('flow.createFromBlank')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  justifyBetween={false}
                  onClick={() => navigateToAgentTemplates()}
                >
                  <ClipboardPlus />
                  {t('flow.createFromTemplate')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  data-testid="agent-import-json"
                  justifyBetween={false}
                  onClick={handleImportJson}
                >
                  <FileInput />
                  {t('flow.importJsonFile')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </ListFilterBar>
        </header>

        <CardContainer className="page-gutter flex-1 overflow-auto">
          {data.length ? (
            data.map((x) =>
              x.type === CompilationGroupCategory ? (
                <CompilationTemplateCard
                  key={x.id}
                  data={x}
                  onClick={handleEditCompilation(x.id)}
                  onDelete={
                    canManageTemplates ? handleDeleteCompilation : undefined
                  }
                />
              ) : (
                <AgentCard
                  key={x.id}
                  data={x}
                  showAgentRenameModal={showAgentRenameModal}
                />
              ),
            )
          ) : listLoading && !searchString ? (
            // The region exists before the data does, so the page size can be
            // measured from it and the first request already asks for a whole page.
            <CardGridPlaceholder />
          ) : (
            <EmptyAppCard
              showIcon
              isSearch={Boolean(searchString)}
              type={EmptyCardType.Agent}
              onClick={handleOpenCreateMenu}
              testId="agents-empty-create"
            />
          )}
        </CardContainer>

        {data.length ? (
          <footer className="page-gutter page-list-footer">
            <RAGFlowPagination
              {...pick(pagination, 'current', 'pageSize')}
              total={pagination.total}
              onChange={handlePageChange}
            />
          </footer>
        ) : null}
      </article>

      {agentRenameVisible && (
        <RenameDialog
          hideModal={hideAgentRenameModal}
          onOk={onAgentRenameOk}
          initialName={initialAgentName}
          loading={agentRenameLoading}
        ></RenameDialog>
      )}
      {creatingVisible && (
        <CreateAgentDialog
          loading={loading}
          visible={creatingVisible}
          hideModal={hideCreatingModal}
          onOk={handleCreateAgentOrPipeline}
        ></CreateAgentDialog>
      )}
      {fileUploadVisible && (
        <UploadAgentDialog
          hideModal={hideFileUploadModal}
          onOk={onFileUploadOk}
        ></UploadAgentDialog>
      )}
    </>
  );
}

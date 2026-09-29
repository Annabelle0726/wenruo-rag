import { CardContainer } from '@/components/card-container';
import { EmptyCardType } from '@/components/empty/constant';
import { EmptyAppCard } from '@/components/empty/empty';
import ListFilterBar from '@/components/list-filter-bar';
import { RenameDialog } from '@/components/rename-dialog';
import { Button } from '@/components/ui/button';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import { Spin } from '@/components/ui/spin';
import { ListDeletionKey } from '@/constants/list-deletion';
import { useGoToPreviousPageOnEmpty } from '@/hooks/logic-hooks';
import { useFetchChatList } from '@/hooks/use-chat-request';
import { buildOwnersFilter } from '@/utils/list-filter-util';
import { pick } from 'lodash';
import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { ChatCard } from './chat-card';
import { useCreateChatDialog } from './hooks/use-create-chat';
import { useRenameChat } from './hooks/use-rename-chat';

export default function ChatList() {
  const {
    data,
    setPagination,
    pagination,
    handleInputChange,
    searchString,
    setSearchString,
    filterValue,
    setFilterValue,
    handleFilterSubmit,
    loading,
  } = useFetchChatList();
  const { t } = useTranslation();
  const { t: tc } = useTranslation('common');
  // The list is read through one local name: the page renders its frame and then
  // either the grid or the empty card, and both branches need the same array.
  const chats = data?.chats ?? [];
  const owners = [buildOwnersFilter(chats, undefined, tc('owner'))];
  const {
    initialChatName,
    chatRenameVisible,
    showChatRenameModal,
    hideChatRenameModal,
    onChatRenameOk,
    chatRenameLoading,
  } = useRenameChat();
  const {
    createChatVisible,
    showCreateChatModal,
    hideCreateChatModal,
    onCreateChatOk,
    createChatLoading,
  } = useCreateChatDialog();

  const handlePageChange = useCallback(
    (page: number, pageSize?: number) => {
      setPagination({ page, pageSize });
    },
    [setPagination],
  );
  useGoToPreviousPageOnEmpty(data?.chats?.length, loading, {
    deletionKey: ListDeletionKey.ChatList,
    searchString,
    setSearchString,
    filterValue,
    setFilterValue,
  });

  const handleShowCreateModal = useCallback(() => {
    showCreateChatModal();
  }, [showCreateChatModal]);

  const [searchParams, setSearchParams] = useSearchParams();
  const isCreate = searchParams.get('isCreate') === 'true';
  useEffect(() => {
    if (isCreate) {
      handleShowCreateModal();
      searchParams.delete('isCreate');
      setSearchParams(searchParams);
    }
  }, [isCreate, handleShowCreateModal, searchParams, setSearchParams]);

  const renameDialogProps = useMemo(() => {
    if (chatRenameVisible) {
      return {
        hideModal: hideChatRenameModal,
        onOk: onChatRenameOk,
        initialName: initialChatName,
        loading: chatRenameLoading,
        title: initialChatName,
      };
    }
    if (createChatVisible) {
      return {
        hideModal: hideCreateChatModal,
        onOk: onCreateChatOk,
        initialName: '',
        loading: createChatLoading,
        title: t('chat.createChat'),
      };
    }
    return null;
  }, [
    chatRenameVisible,
    createChatVisible,
    hideChatRenameModal,
    onChatRenameOk,
    initialChatName,
    chatRenameLoading,
    hideCreateChatModal,
    onCreateChatOk,
    createChatLoading,
    t,
  ]);

  return (
    <>
      {loading && !chats.length ? (
        <article
          className="size-full flex items-center justify-center"
          data-testid="chats-list"
        >
          <Spin size="large" />
        </article>
      ) : (
        // One full-height column under the header: the filter bar keeps the page
        // framed and the grid or the empty card fills the rest of the region, so
        // an empty list reads as a page with nothing in it rather than a lone box
        // floating in the window. `h-full` is the header-relative remainder of
        // the viewport, because this article sits in the layout's `1fr` row.
        <article
          className="flex h-full w-full min-w-0 flex-col"
          data-testid="chats-list"
        >
          <header className="page-gutter page-toolbar min-w-0">
            <ListFilterBar
              searchVariant="capsule"
              title={t('chat.chatApps')}
              icon="chats"
              onSearchChange={handleInputChange}
              searchString={searchString}
              filters={owners}
              value={filterValue}
              onChange={handleFilterSubmit}
            >
              <Button
                className="ceramic-cta h-8 rounded-[2px] px-3 text-xs font-medium gap-1.5"
                data-testid="create-chat"
                onClick={handleShowCreateModal}
              >
                <Plus className="size-3.5" />
                {t('chat.createChat')}
              </Button>
            </ListFilterBar>
          </header>

          {chats.length ? (
            <>
              <CardContainer className="page-gutter flex-1 overflow-auto">
                {chats.map((x) => (
                  <ChatCard
                    key={x.id}
                    data={x}
                    showChatRenameModal={showChatRenameModal}
                  />
                ))}
              </CardContainer>

              <footer className="page-gutter page-list-footer">
                <RAGFlowPagination
                  {...pick(pagination, 'current', 'pageSize')}
                  total={pagination.total}
                  onChange={handlePageChange}
                />
              </footer>
            </>
          ) : (
            // A grid item in the same container the cards use: the create tile is
            // exactly as wide and as tall as a chat card.
            <CardContainer className="page-gutter flex-1 overflow-auto">
              <EmptyAppCard
                showIcon
                isSearch={Boolean(searchString)}
                type={EmptyCardType.Chat}
                onClick={() => handleShowCreateModal()}
                testId="chats-empty-create"
              />
            </CardContainer>
          )}
        </article>
      )}

      {renameDialogProps && (
        <RenameDialog {...renameDialogProps}></RenameDialog>
      )}
    </>
  );
}

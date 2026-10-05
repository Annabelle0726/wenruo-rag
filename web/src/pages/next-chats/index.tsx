import { CardContainer } from '@/components/card-container';
import { CardGridPlaceholder } from '@/components/card-grid-placeholder';
import { EmptyCardType } from '@/components/empty/constant';
import { EmptyAppCard } from '@/components/empty/empty';
import ListFilterBar from '@/components/list-filter-bar';
import { RenameDialog } from '@/components/rename-dialog';
import { Button } from '@/components/ui/button';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
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
      {/* The frame, the toolbar and the grid region are rendered whether or not
          the list has arrived. The page size is the number of complete cards this
          region holds, so the region has to exist before the request goes out
          (`useListCapacity` measures it and holds the query until it knows), and
          the list no longer jumps when the data lands in a different shape. */}
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

        <CardContainer className="page-gutter flex-1 overflow-auto">
          {loading && !chats.length ? (
            <CardGridPlaceholder />
          ) : chats.length ? (
            chats.map((x) => (
              <ChatCard
                key={x.id}
                data={x}
                showChatRenameModal={showChatRenameModal}
              />
            ))
          ) : (
            // A grid item in the same container the cards use: the create tile is
            // exactly as wide and as tall as a chat card.
            <EmptyAppCard
              showIcon
              isSearch={Boolean(searchString)}
              type={EmptyCardType.Chat}
              onClick={() => handleShowCreateModal()}
              testId="chats-empty-create"
            />
          )}
        </CardContainer>

        {chats.length ? (
          <footer className="page-gutter page-list-footer">
            <RAGFlowPagination
              {...pick(pagination, 'current', 'pageSize')}
              total={pagination.total}
              onChange={handlePageChange}
            />
          </footer>
        ) : null}
      </article>

      {renameDialogProps && (
        <RenameDialog {...renameDialogProps}></RenameDialog>
      )}
    </>
  );
}

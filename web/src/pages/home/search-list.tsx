import { IconFont } from '@/components/icon-font';
import { RenameDialog } from '@/components/rename-dialog';
import { useEffect } from 'react';
import { useFetchSearchList, useRenameSearch } from '../next-searches/hooks';
import { SearchCard } from '../next-searches/search-card';

export function SearchList({
  setListLength,
  setLoading,
}: {
  setListLength: (length: number) => void;
  setLoading?: (loading: boolean) => void;
}) {
  const { data, refetch: refetchList, isLoading } = useFetchSearchList();
  const {
    openCreateModal,
    showSearchRenameModal,
    hideSearchRenameModal,
    searchRenameLoading,
    onSearchRenameOk,
    initialSearchName,
  } = useRenameSearch();
  const onSearchRenameConfirm = (name: string) => {
    onSearchRenameOk(name, () => {
      refetchList();
    });
  };

  useEffect(() => {
    setListLength(data?.data?.search_apps?.length || 0);
    setLoading?.(isLoading || false);
  }, [data, setListLength, isLoading, setLoading]);
  return (
    <>
      {data?.data.search_apps.slice(0, 10).map((x) => (
        // The same card the search list page renders.
        <SearchCard
          key={x.id}
          data={x}
          showSearchRenameModal={showSearchRenameModal}
        />
      ))}
      {openCreateModal && (
        <RenameDialog
          hideModal={hideSearchRenameModal}
          onOk={onSearchRenameConfirm}
          initialName={initialSearchName}
          loading={searchRenameLoading}
          title={<IconFont name="search" className="size-6"></IconFont>}
        ></RenameDialog>
      )}
    </>
  );
}

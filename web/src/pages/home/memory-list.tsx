import { useEffect } from 'react';
import { AddOrEditModal } from '../memories/add-or-edit-modal';
import { useFetchMemoryList, useRenameMemory } from '../memories/hooks';
import { ICreateMemoryProps } from '../memories/interface';
import { MemoryCard } from '../memories/memory-card';

export function MemoryList({
  setListLength,
  setLoading,
}: {
  setListLength: (length: number) => void;
  setLoading?: (loading: boolean) => void;
}) {
  const { data, refetch: refetchList, isLoading } = useFetchMemoryList();
  const {
    openCreateModal,
    showMemoryRenameModal,
    hideMemoryModal,
    memoryRenameLoading,
    onMemoryRenameOk,
    initialMemory,
  } = useRenameMemory();
  const onMemoryConfirm = (data: ICreateMemoryProps) => {
    onMemoryRenameOk(data, () => {
      refetchList();
    });
  };

  useEffect(() => {
    setListLength(data?.data?.memory_list?.length || 0);
    setLoading?.(isLoading || false);
  }, [data, setListLength, isLoading, setLoading]);
  return (
    <>
      {data?.data.memory_list.slice(0, 10).map((x) => (
        // The same card the memory list page renders, owner badge included.
        <MemoryCard
          key={x.id}
          data={x}
          showMemoryRenameModal={showMemoryRenameModal}
        />
      ))}
      {openCreateModal && (
        <AddOrEditModal
          initialMemory={initialMemory}
          isCreate={false}
          open={openCreateModal}
          loading={memoryRenameLoading}
          onClose={hideMemoryModal}
          onSubmit={onMemoryConfirm}
        />
      )}
    </>
  );
}

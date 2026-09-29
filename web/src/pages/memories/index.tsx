/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import { CardContainer } from '@/components/card-container';
import { EmptyCardType } from '@/components/empty/constant';
import { EmptyAppCard } from '@/components/empty/empty';
import ListFilterBar from '@/components/list-filter-bar';
import { Button } from '@/components/ui/button';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import { ListDeletionKey } from '@/constants/list-deletion';
import { useTranslate } from '@/hooks/common-hooks';
import { useGoToPreviousPageOnEmpty } from '@/hooks/logic-hooks';
import { pick } from 'lodash';
import { Plus } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { AddOrEditModal } from './add-or-edit-modal';
import { defaultMemoryFields } from './constants';
import { useFetchMemoryList, useRenameMemory, useSelectFilters } from './hooks';
import { ICreateMemoryProps, IMemory } from './interface';
import { MemoryCard } from './memory-card';

export default function MemoryList() {
  const { t } = useTranslate('memories');
  const [addOrEditType, setAddOrEditType] = useState<'add' | 'edit'>('add');
  const {
    data: list,
    isLoading,
    pagination,
    searchString,
    setSearchString,
    handleInputChange,
    setPagination,
    refetch: refetchList,
    filterValue,
    setFilterValue,
    handleFilterSubmit,
  } = useFetchMemoryList();

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

  const openCreateModalFun = useCallback(() => {
    setAddOrEditType('add');
    showMemoryRenameModal(defaultMemoryFields as unknown as IMemory);
  }, [showMemoryRenameModal]);

  const handlePageChange = useCallback(
    (page: number, pageSize?: number) => {
      setPagination({ page, pageSize });
    },
    [setPagination],
  );

  useGoToPreviousPageOnEmpty(list?.data?.memory_list?.length, isLoading, {
    deletionKey: ListDeletionKey.MemoryList,
    searchString,
    setSearchString,
    filterValue,
    setFilterValue,
  });

  const [searchUrl, setMemoryUrl] = useSearchParams();
  const { filters } = useSelectFilters(list?.data?.memory_list ?? []);
  const isCreate = searchUrl.get('isCreate') === 'true';

  useEffect(() => {
    if (isCreate) {
      openCreateModalFun();
      setMemoryUrl(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('isCreate');
          return next;
        },
        { replace: true },
      );
    }
  }, [isCreate, openCreateModalFun, setMemoryUrl]);

  return (
    <>
      {list?.data?.memory_list?.length || searchString ? (
        <article
          className="size-full min-w-0 flex flex-col"
          data-testid="memory-list"
        >
          <header className="page-gutter page-toolbar min-w-0">
            <ListFilterBar
              icon="memory"
              title={t('memory')}
              onSearchChange={handleInputChange}
              searchString={searchString}
              filters={filters}
              onChange={handleFilterSubmit}
              value={filterValue}
              searchVariant="capsule"
            >
              <Button
                className="ceramic-cta h-8 rounded-[2px] px-3 text-xs font-medium gap-1.5"
                onClick={() => openCreateModalFun()}
              >
                <Plus className="size-3.5" />
                {t('createMemory')}
              </Button>
            </ListFilterBar>
          </header>

          {list?.data?.memory_list?.length ? (
            <>
              <CardContainer className="page-gutter flex-1 overflow-auto">
                {list?.data.memory_list.map((x) => (
                  <MemoryCard
                    key={x.id}
                    data={x}
                    showMemoryRenameModal={() => {
                      setAddOrEditType('edit');
                      showMemoryRenameModal(x);
                    }}
                  />
                ))}
              </CardContainer>

              <footer className="page-gutter page-list-footer">
                <RAGFlowPagination
                  {...pick(pagination, 'current', 'pageSize')}
                  total={list?.data.total_count}
                  onChange={handlePageChange}
                />
              </footer>
            </>
          ) : (
            <CardContainer className="page-gutter flex-1 overflow-auto">
              <EmptyAppCard
                showIcon
                isSearch
                type={EmptyCardType.Memory}
                onClick={() => openCreateModalFun()}
              />
            </CardContainer>
          )}
        </article>
      ) : (
        <article
          className="size-full min-w-0 flex flex-col"
          data-testid="memory-list"
        >
          <CardContainer className="page-gutter flex-1 overflow-auto pt-8">
            <EmptyAppCard
              showIcon
              type={EmptyCardType.Memory}
              onClick={() => openCreateModalFun()}
            />
          </CardContainer>
        </article>
      )}

      {openCreateModal && (
        <AddOrEditModal
          initialMemory={initialMemory}
          isCreate={addOrEditType === 'add'}
          open={openCreateModal}
          loading={memoryRenameLoading}
          onClose={hideMemoryModal}
          onSubmit={onMemoryConfirm}
        />
      )}
    </>
  );
}

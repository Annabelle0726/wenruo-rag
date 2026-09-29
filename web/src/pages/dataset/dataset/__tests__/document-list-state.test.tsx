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

/**
 * What the file list SAYS, per state — the transport is the only stub.
 *
 * The reported bug was a sentence, not a number: a dataset the caller could not
 * read showed "暂无数据 / 共 0 条", i.e. the page asserted an empty file list it
 * had never established. These tests drive the real hook and the real table over
 * a stubbed `listDocument`, so they fail if the page ever again reports on
 * contents it did not receive: five documents must be five rows, and only a
 * `code=0` answer with `total=0` may say "no data".
 *
 * The table's columns are stubbed because the question here is the state the
 * table renders, not what a row's action cell does; every other part of the
 * table — the body, the state branches and the pager — is the production one.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { useFetchDocumentList } from '@/hooks/use-document-request';
import { DatasetTable } from '../dataset-table';

const mockListDocument = jest.fn();

jest.mock('react-router', () => ({
  ...jest.requireActual('react-router'),
  createBrowserRouter: () => ({}),
}));

jest.mock('@/services/knowledge-service', () => ({
  __esModule: true,
  default: {},
  listDocument: (...args: unknown[]) => mockListDocument(...args),
}));

jest.mock('../use-dataset-table-columns', () => ({
  useDatasetTableColumns: () => [
    {
      id: 'name',
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }: { row: { original: { name: string } } }) =>
        row.original.name,
    },
  ],
}));

jest.mock('@/hooks/use-dataset-preferences', () => ({
  useDatasetPreferences: () => ({ isHidden: () => false }),
}));

jest.mock('../../contexts/knowledge-base-context', () => ({
  useKnowledgeBaseContext: () => ({ knowledgeBase: { id: 'ds-real-1' } }),
}));

const noop = () => {};

const documentsOf = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    id: `doc-${index + 1}`,
    name: `file-${index + 1}.pdf`,
    dataset_id: 'ds-real-1',
    status: '1',
  }));

const answer = (code: number, data: unknown, message = '') => ({
  data: { code, data, message },
});

function DatasetFileList() {
  const { documents, pagination, setPagination, state, retry } =
    useFetchDocumentList(false);

  return (
    <DatasetTable
      documents={documents}
      pagination={pagination}
      setPagination={setPagination}
      state={state}
      retry={retry}
      rowSelection={{}}
      setRowSelection={noop}
      showManageMetadataModal={noop}
    />
  );
}

function renderFileList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/dataset/ds-real-1']}>
        <Routes>
          <Route path="/dataset/:id" element={<DatasetFileList />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const emptyCopy = 'No data available';
const loadingCopy = /Loading the file list/;
const failureCopy = /Failed to load the file list/;
const forbiddenCopy = /do not have permission/;

beforeEach(() => {
  mockListDocument.mockReset();
});

it('renders one row per document when code=0 answers with five', async () => {
  mockListDocument.mockResolvedValue(
    answer(0, { docs: documentsOf(5), total: 5 }),
  );

  renderFileList();

  await waitFor(() =>
    expect(screen.getAllByTestId('document-row')).toHaveLength(5),
  );
  expect(screen.getByText('file-1.pdf')).toBeInTheDocument();
  expect(screen.queryByText(emptyCopy)).not.toBeInTheDocument();
  expect(screen.getByText('Total 5')).toBeInTheDocument();
});

it('says no data only for a code=0 answer whose total is zero', async () => {
  mockListDocument.mockResolvedValue(answer(0, { docs: [], total: 0 }));

  renderFileList();

  expect(await screen.findByText(emptyCopy)).toBeInTheDocument();
  expect(screen.queryAllByTestId('document-row')).toHaveLength(0);
  expect(screen.getByText('Total 0')).toBeInTheDocument();
});

it('says it is a permission refusal, not empty data, for code=108', async () => {
  mockListDocument.mockResolvedValue(answer(108, null, 'no permission'));

  renderFileList();

  expect(await screen.findByText(forbiddenCopy)).toBeInTheDocument();
  expect(screen.queryByText(emptyCopy)).not.toBeInTheDocument();
  // No fabricated count either: nobody established that this list holds 0.
  expect(screen.queryByText(/^Total /)).not.toBeInTheDocument();
});

it('says the read failed, not empty data, when the code fails', async () => {
  mockListDocument.mockResolvedValue(answer(102, null, 'data error'));

  renderFileList();

  expect(await screen.findByText(failureCopy)).toBeInTheDocument();
  expect(screen.queryByText(emptyCopy)).not.toBeInTheDocument();
  expect(screen.queryByText(/^Total /)).not.toBeInTheDocument();
});

it('recovers into rows when the failed read is retried', async () => {
  mockListDocument
    .mockResolvedValueOnce(answer(500, null, 'server error'))
    .mockResolvedValueOnce(answer(0, { docs: documentsOf(5), total: 5 }));

  renderFileList();

  const retry = await screen.findByRole('button', { name: 'Retry' });
  retry.click();

  await waitFor(() =>
    expect(screen.getAllByTestId('document-row')).toHaveLength(5),
  );
  expect(screen.queryByText(failureCopy)).not.toBeInTheDocument();
  expect(screen.queryByText(emptyCopy)).not.toBeInTheDocument();
});

it('says it is loading, not empty data, while the read is in flight', async () => {
  mockListDocument.mockReturnValue(new Promise(() => {}));

  renderFileList();

  expect(await screen.findByText(loadingCopy)).toBeInTheDocument();
  expect(screen.queryByText(emptyCopy)).not.toBeInTheDocument();
  expect(screen.queryByText(/^Total /)).not.toBeInTheDocument();
});

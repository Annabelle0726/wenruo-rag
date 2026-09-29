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
 * The document list's state model, over the real hook and a stubbed transport.
 *
 * The bug these pin down is not a wrong number: it is a wrong *kind* of answer.
 * The list endpoint reports a refusal as HTTP 200 + `code=108`, and the hook used
 * to map every failing code to `{ docs: [], total: 0 }`, so a read nobody was
 * allowed to perform arrived at the page as a successful empty dataset and
 * rendered "暂无数据 / 共 0 条". The states below must therefore stay
 * distinguishable: only `code=0 && total=0` is empty, and neither a refusal nor
 * a transport failure nor an unanswered request is ever empty.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { useFetchDocumentList } from '../use-document-request';

const mockListDocument = jest.fn();

// `route-hook` (reached through `logic-hooks`) imports `@/routes`, which builds a
// real browser router at module scope. jsdom has no `Request`, so react-router
// throws while building it and takes this suite down before one assertion runs.
// This test is about the document list, not the app's router, so the browser
// router - and only it - is stubbed; the `MemoryRouter` below is the real one.
jest.mock('react-router', () => ({
  ...jest.requireActual('react-router'),
  createBrowserRouter: () => ({}),
}));

jest.mock('@/services/knowledge-service', () => ({
  __esModule: true,
  default: {},
  listDocument: (...args: unknown[]) => mockListDocument(...args),
}));

const documentsOf = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    id: `doc-${index + 1}`,
    name: `file-${index + 1}.pdf`,
    dataset_id: 'ds-real-1',
  }));

const answer = (code: number, data: unknown, message = '') => ({
  data: { code, data, message },
});

// The dataset's own route is `/dataset/:id`, so the id the hook gates on comes
// from the path, and `idle` is the state of a route that carries none.
const wrapperAt = (path: string, entry: string) =>
  function Wrapper({ children }: { children: React.ReactNode }) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path={path} element={<>{children}</>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };

function renderDocumentList(
  entry = '/dataset/ds-real-1',
  path = '/dataset/:id',
) {
  return renderHook(() => useFetchDocumentList(false), {
    wrapper: wrapperAt(path, entry),
  });
}

beforeEach(() => {
  mockListDocument.mockReset();
});

it('reports success with the rows a code=0 answer carried', async () => {
  const docs = documentsOf(5);
  mockListDocument.mockResolvedValue(answer(0, { docs, total: 5 }));

  const { result } = renderDocumentList();

  await waitFor(() => expect(result.current.state.status).toBe('success'));
  expect(result.current.documents).toHaveLength(5);
  expect(result.current.pagination.total).toBe(5);
});

it('reports empty only when code=0 says so itself', async () => {
  mockListDocument.mockResolvedValue(answer(0, { docs: [], total: 0 }));

  const { result } = renderDocumentList();

  await waitFor(() => expect(result.current.state.status).toBe('empty'));
  expect(result.current.documents).toHaveLength(0);
  expect(result.current.pagination.total).toBe(0);
});

it('reports a refused read as forbidden, never as empty data', async () => {
  mockListDocument.mockResolvedValue(answer(108, null, 'no permission'));

  const { result } = renderDocumentList();

  await waitFor(() => expect(result.current.state.status).toBe('forbidden'));
  expect(result.current.state.code).toBe(108);
  expect(result.current.state.status).not.toBe('empty');
  expect(result.current.state.status).not.toBe('success');
});

it('reports a failing code other than a refusal as an error, never as empty', async () => {
  mockListDocument.mockResolvedValue(answer(102, null, 'data error'));

  const { result } = renderDocumentList();

  await waitFor(() => expect(result.current.state.status).toBe('error'));
  expect(result.current.state.code).toBe(102);
  expect(result.current.state.status).not.toBe('empty');
});

it('reports a transport failure as an error, never as empty', async () => {
  mockListDocument.mockRejectedValue(new Error('offline'));

  const { result } = renderDocumentList();

  await waitFor(() => expect(result.current.state.status).toBe('error'));
  expect(result.current.state.message).toBe('offline');
});

it('reports a read that has not settled as loading, never as empty', async () => {
  let settle: (value: unknown) => void = () => {};
  mockListDocument.mockReturnValue(
    new Promise((resolve) => {
      settle = resolve;
    }),
  );

  const { result } = renderDocumentList();

  expect(result.current.state.status).toBe('loading');
  expect(result.current.state.status).not.toBe('empty');

  settle(answer(0, { docs: documentsOf(2), total: 2 }));
  await waitFor(() => expect(result.current.state.status).toBe('success'));
});

it('distinguishes a list nobody requested from an empty one', () => {
  const { result } = renderDocumentList('/dataset', '/dataset');

  expect(result.current.state.status).toBe('idle');
  expect(mockListDocument).not.toHaveBeenCalled();
});

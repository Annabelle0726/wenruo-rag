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
 * The state model of a dataset's document list.
 *
 * A document list has six states and they are not interchangeable: never
 * requested, still loading, refused, failed, legitimately empty and answered
 * with rows. The backend returns HTTP 200 for all of them — a refusal is
 * `code=108` in the body rather than a 4xx — so a caller that reads only the
 * documents, and maps every failing code to `{ docs: [], total: 0 }`, renders a
 * refusal and a transport failure as "no data". That is a fabricated success:
 * it is indistinguishable from an empty dataset, so a user with no permission
 * is told their dataset is empty.
 *
 * This module is the single place that reads the distinction. `page` is the
 * evidence a read succeeded, because only a `code=0` answer ever produces one.
 */

/** `common/constants.py` RetCode values that mean "this caller may not read it". */
const FORBIDDEN_CODES: readonly number[] = [
  108, // RetCode.PERMISSION_ERROR
  403, // RetCode.FORBIDDEN
];

export type DocumentListStatus =
  | 'idle'
  | 'loading'
  | 'forbidden'
  | 'error'
  | 'empty'
  | 'success';

export interface DocumentListState {
  status: DocumentListStatus;
  /** The failing code, when the server answered with one rather than a transport error. */
  code?: number;
  /** The server's own sentence, or the transport error's message. */
  message?: string;
}

/**
 * A document-list response whose body carried a code other than 0.
 *
 * The HTTP status is 200, so the transport cannot tell anyone this failed: the
 * query has to raise it deliberately, and this type is what keeps the code
 * readable on the way to the state model.
 */
export class DocumentListRequestError extends Error {
  readonly code: number;

  constructor(code: number, message?: string) {
    super(message || `Document list request failed with code ${code}`);
    this.name = 'DocumentListRequestError';
    this.code = code;
  }
}

export const isForbiddenDocumentCode = (code: number | undefined): boolean =>
  typeof code === 'number' && FORBIDDEN_CODES.includes(code);

/** One page of documents as the backend reported it. Only `code=0` produces one. */
export interface DocumentListPage {
  docs: readonly unknown[];
  total: number;
}

export interface DocumentListQueryFacts {
  /** The query is gated on a dataset id from the route; false means it never ran. */
  enabled: boolean;
  isError: boolean;
  error: unknown;
  /** Undefined until a `code=0` answer arrives — never a stand-in for "empty". */
  page: DocumentListPage | undefined;
}

const failureStateOf = (error: unknown): DocumentListState => {
  const code =
    error instanceof DocumentListRequestError ? error.code : undefined;
  const message = error instanceof Error ? error.message : undefined;

  return isForbiddenDocumentCode(code)
    ? { status: 'forbidden', code, message }
    : { status: 'error', code, message };
};

/**
 * Which state the list is in.
 *
 * The order decides what a caller may say. "Never requested" comes from the
 * route, an arrived answer comes from the data, and a failure is consulted
 * last — so a failed read is never reported as an empty list, and a read that
 * has not settled is never reported as one either. Anything else (no answer, no
 * failure) is still in flight, which is not the same as empty.
 */
export const documentListStateOf = (
  facts: DocumentListQueryFacts,
): DocumentListState => {
  const { enabled, isError, error, page } = facts;

  if (!enabled) {
    return { status: 'idle' };
  }

  if (page) {
    // `page` exists only for `code=0`, so an empty page here is a real empty
    // dataset rather than a swallowed failure.
    return page.total === 0 && page.docs.length === 0
      ? { status: 'empty' }
      : { status: 'success' };
  }

  if (isError) {
    return failureStateOf(error);
  }

  return { status: 'loading' };
};

/**
 * Whether the list has a settled, successful read to show.
 *
 * Only then may a page render rows, an empty state or a record count: a
 * loading, refused or failed read has nothing to report about its contents.
 */
export const documentListIsSettled = (state: DocumentListState): boolean =>
  state.status === 'success' || state.status === 'empty';

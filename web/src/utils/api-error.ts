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

import message from '@/components/ui/message';
import i18n from '@/locales/config';
import notification from '@/utils/notification';
import {
  modelServiceErrorMessageKey,
  modelServiceErrorOf,
} from '@/utils/model-service-error';

/** How much of an error message a notification will print. */
const MAX_NOTIFICATION_LENGTH = 300;

/**
 * Caps a message for a toast.
 *
 * A notification is not a log viewer. An unmapped failure can carry a stack, a
 * whole upstream response body or a database error, and every character of it
 * used to be rendered in a panel a few lines tall.
 */
export const summarize = (text?: unknown) => {
  const value = typeof text === 'string' ? text : String(text ?? '');
  return value.length > MAX_NOTIFICATION_LENGTH
    ? `${value.slice(0, MAX_NOTIFICATION_LENGTH)}…`
    : value;
};

interface ApiErrorBody {
  code?: number;
  message?: string;
  error_type?: unknown;
}

/**
 * Reports a failed API body the way its reader can use it.
 *
 * Both HTTP layers — the axios client and the fetch client — raise the same
 * notifications for the same business error codes, so the decision lives here
 * rather than twice: a refusal the backend classified gets one short sentence
 * in the reader's language, anything else keeps the hint-and-code notification
 * with its message capped.
 *
 * HTTP 401 is the caller's: it owns the redirect guard, so this leaves it
 * alone.
 */
export const reportApiError = (
  body: ApiErrorBody | null | undefined,
  { skip = false }: { skip?: boolean } = {},
) => {
  if (skip || !body || body.code === 401) return;

  const modelServiceError = modelServiceErrorOf(body);
  if (modelServiceError) {
    message.error(i18n.t(modelServiceErrorMessageKey(modelServiceError)));
    return;
  }

  if (body.code === 100) {
    message.error(summarize(body.message));
    return;
  }

  if (body.code !== 0) {
    notification.error({
      message: `${i18n.t('message.hint')} : ${body.code}`,
      description: summarize(body.message),
      duration: 3,
    });
  }
};

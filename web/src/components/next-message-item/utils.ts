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

import { UploadResponseDataType } from '@/interfaces/database/chat';
import { IDocumentInfo } from '@/interfaces/database/document';
import { citedChunkIndex, currentReg } from '@/utils/chat';
import { getExtension } from '@/utils/document-util';

/**
 * The indexes of the chunks an answer cites, into the reference pool.
 *
 * Markers are 1-based in the chat/agentic flows (`kb_prompt` renders "ID: 1" …
 * "ID: n"), so `[ID:5]` yields index 4 — the index into `reference.chunks` (see
 * citedChunkIndex).
 */
export const extractCitedChunkIndexes = (content: string) => {
  const matches = content?.match(currentReg);
  if (matches) {
    // citedChunkIndex reports "no index" as -1, which must never be treated as a
    // pool index, so unusable markers are dropped.
    return matches
      .map((match) => citedChunkIndex(match))
      .filter((index) => index >= 0);
  }
  return [];
};

const ImageExtensions = [
  'png',
  'jpg',
  'jpeg',
  'gif',
  'bmp',
  'webp',
  'svg',
  'ico',
  'avif',
];

export function getFileMimeType(
  file: File | IDocumentInfo | UploadResponseDataType,
): string {
  if (file instanceof File) {
    return file.type;
  }
  if ('mime_type' in file && typeof file.mime_type === 'string') {
    return file.mime_type;
  }
  return '';
}

export function isImageFile(
  file: File | IDocumentInfo | UploadResponseDataType,
): boolean {
  const mimeType = getFileMimeType(file);
  if (mimeType) {
    return mimeType.startsWith('image/');
  }
  return ImageExtensions.includes(getExtension(file.name));
}

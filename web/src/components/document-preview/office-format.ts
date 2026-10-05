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

import JSZip from 'jszip';

export type OfficeFormat =
  | 'docx'
  | 'xlsx'
  | 'pptx'
  | 'legacy-office'
  | 'unknown';

// Every OOXML package is a ZIP: modern .docx, .xlsx and .pptx all start "PK".
const ZIP_MAGIC = [0x50, 0x4b];
// Word, Excel and PowerPoint 97-2003 share the OLE2 compound-file container.
const OLE2_MAGIC = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];

const startsWith = (bytes: Uint8Array, magic: readonly number[]): boolean =>
  bytes.length >= magic.length &&
  magic.every((byte, index) => bytes[index] === byte);

/**
 * Which Office format a document really is, read from its own bytes rather than
 * from the stored record.
 *
 * The dataset record's `type` is only a hint: a spreadsheet can be recorded as
 * a Word document, and the modern and legacy formats share one extension, so a
 * `.doc` may well be a Word 97-2003 file that no browser-side renderer can read.
 * The caller passes the bytes it already fetched for the preview.
 */
export const detectOfficeFormat = async (
  data: ArrayBuffer,
): Promise<OfficeFormat> => {
  const header = new Uint8Array(data, 0, Math.min(8, data.byteLength));

  if (startsWith(header, OLE2_MAGIC)) {
    return 'legacy-office';
  }

  if (!startsWith(header, ZIP_MAGIC)) {
    return 'unknown';
  }

  // A ZIP archive: its entry names say which OOXML flavour it holds, and reading
  // the central directory is far cheaper than unpacking a document.
  try {
    const zip = await JSZip.loadAsync(data);
    const names = Object.keys(zip.files);

    if (names.includes('word/document.xml')) {
      return 'docx';
    }
    if (names.some((name) => name.startsWith('xl/'))) {
      return 'xlsx';
    }
    if (names.some((name) => name.startsWith('ppt/'))) {
      return 'pptx';
    }
  } catch (error) {
    console.error('Failed to read the Office package entries', error);
  }

  return 'unknown';
};

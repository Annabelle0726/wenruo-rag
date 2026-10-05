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
 * @param  {String}  url
 * @param  {Boolean} isNoCaseSensitive
 * @return {Object}
 */
// import numeral from 'numeral';

import { Base64 } from 'js-base64';
import JSEncrypt from 'jsencrypt';

export const getWidth = () => {
  return { width: window.innerWidth };
};
export const rsaPsw = async (password: string): Promise<string> => {
  const response = await fetch('/api/v1/system/public-key', { cache: 'no-store' });
  if (!response.ok) throw new Error('Unable to load login encryption key');
  const result = await response.json();
  if (result.code !== 0 || typeof result.data !== 'string')
    throw new Error('Invalid login encryption key');
  const encryptor = new JSEncrypt();
  encryptor.setPublicKey(result.data);
  const ciphertext = encryptor.encrypt(Base64.encode(password));
  if (!ciphertext) throw new Error('Unable to encrypt password');
  return ciphertext;
};

export default {
  getWidth,
  rsaPsw,
};

export const getFileExtension = (filename: string) =>
  filename.slice(filename.lastIndexOf('.') + 1).toLowerCase();

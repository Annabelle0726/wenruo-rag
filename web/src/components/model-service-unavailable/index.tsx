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

import Empty from '@/components/empty/empty';
import { EmptyType } from '@/components/empty/constant';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  ModelServiceErrorType,
  modelServiceErrorMessageKey,
} from '@/utils/model-service-error';
import { RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface ModelServiceUnavailableProps {
  errorType: ModelServiceErrorType;
  /** What is unavailable, e.g. "由于向量化服务受限，搜索暂不可用". */
  title: string;
  onRetry?: () => void;
  className?: string;
}

/**
 * The page-level stand-in for a request the vector service refused.
 *
 * A toast disappears and leaves the reader looking at a page that looks
 * empty-but-fine; this holds the space where the results would have been and
 * says which capability is down, so the state is not mistaken for "no matches".
 */
export default function ModelServiceUnavailable({
  errorType,
  title,
  onRetry,
  className,
}: ModelServiceUnavailableProps) {
  const { t } = useTranslation();

  return (
    <div
      className={cn('flex h-2/5 items-center justify-center', className)}
      data-testid="model-service-unavailable"
    >
      <Empty type={EmptyType.SearchData} iconWidth={80}>
        <div className="text-base text-text-primary">{title}</div>
        <div className="max-w-md text-sm text-text-secondary">
          {t(modelServiceErrorMessageKey(errorType))}
        </div>
        {onRetry && (
          <Button
            variant="outline"
            className="mt-1 gap-1.5"
            onClick={onRetry}
            data-testid="model-service-retry"
          >
            <RotateCcw className="size-3.5" />
            {t('common.retry')}
          </Button>
        )}
      </Empty>
    </div>
  );
}

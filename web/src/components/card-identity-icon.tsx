/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
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

import { cn } from '@/lib/utils';
import {
  Bot,
  Brain,
  Compass,
  Database,
  FileStack,
  MessageSquareCode,
  User,
  type LucideIcon,
} from 'lucide-react';
import { useState } from 'react';

/** The card families that carry a vector identity mark. */
export type CardIdentityKind =
  | 'chat'
  | 'search'
  | 'memory'
  | 'agent'
  | 'template'
  | 'dataset'
  | 'user';

const CARD_IDENTITY_ICONS: Record<CardIdentityKind, LucideIcon> = {
  chat: MessageSquareCode,
  search: Compass,
  memory: Brain,
  agent: Bot,
  template: FileStack,
  dataset: Database,
  user: User,
};

const HALO_CLASS =
  'flex size-8 shrink-0 items-center justify-center overflow-hidden bg-background';

type CardIdentityIconProps = {
  kind: CardIdentityKind;
  /** Owner-supplied image. When present it replaces the vector mark. */
  avatar?: string;
  className?: string;
  /**
   * Size of the glyph inside the frame. The frame is sized with `className`; a
   * sidebar header is a taller frame than a card row, so it asks for a larger mark
   * instead of stretching a 16px one.
   */
  iconClassName?: string;
  'data-testid'?: string;
};

export function CardIdentityIcon({
  kind,
  avatar,
  className,
  iconClassName,
  'data-testid': testId,
}: CardIdentityIconProps) {
  const [imageFailed, setImageFailed] = useState(false);
  const Icon = CARD_IDENTITY_ICONS[kind];

  if (avatar && !imageFailed) {
    return (
      <span className={cn(HALO_CLASS, className)} data-testid={testId}>
        <img
          src={avatar}
          alt=""
          className="block size-full object-cover"
          onError={() => setImageFailed(true)}
        />
      </span>
    );
  }

  return (
    <span
      className={cn(HALO_CLASS, 'bg-cable-icon', className)}
      data-testid={testId}
    >
      <Icon
        className={cn('size-4 text-cable-icon-foreground', iconClassName)}
        aria-hidden
      />
    </span>
  );
}
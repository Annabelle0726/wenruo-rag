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
import * as AvatarPrimitive from '@radix-ui/react-avatar';
import { LucideUser } from 'lucide-react';
import { forwardRef, memo, useMemo } from 'react';
import { Avatar, AvatarFallback, AvatarImage } from './ui/avatar';

const getInitials = (name?: string) => {
  if (typeof name !== 'string' || !name) return '';
  const parts = name?.trim().split(/\s+/);
  if (parts.length === 1) {
    return parts[0][0].toUpperCase();
  }
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

/**
 * The single character a person's avatar falls back to.
 *
 * Candidates are tried in the order the caller passes them — nickname, then
 * name, then email — and the first one holding text wins. `Array.from` keeps a
 * surrogate pair (an emoji, or most CJK extensions) in one piece.
 */
export const getAvatarInitial = (...candidates: Array<string | undefined>) => {
  for (const candidate of candidates) {
    const value = candidate?.trim();
    if (value) {
      return Array.from(value)[0].toUpperCase();
    }
  }

  return '';
};

export const RAGFlowAvatar = memo(
  forwardRef<
    React.ElementRef<typeof AvatarPrimitive.Root>,
    React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root> & {
      name?: string;
      /** Second source for a person's initial, used when the name is empty. */
      email?: string;
      avatar?: string;
      isPerson?: boolean;
    }
  >(({ name, email, avatar, isPerson = false, className, ...props }, ref) => {
    // Generate initial letter logic
    const { initials } = useMemo(
      () => ({
        // A person falls back to one character of their name or email; other
        // avatars (datasets, agents) keep the two-letter form of their name.
        initials: isPerson ? getAvatarInitial(name, email) : getInitials(name),
      }),
      [email, isPerson, name],
    );

    return (
      <Avatar
        ref={ref}
        {...props}
        className={cn(className, { 'rounded-md': !isPerson })}
      >
        <AvatarImage src={avatar} />
        <AvatarFallback
          className={cn(
            'flex items-center justify-center border',
            // 国网实色规则：人用品牌绿实底，机器实体用浅灰实底 + 1px 描边，
            // 不再按名字散列到四组彩虹渐变。
            isPerson
              ? 'border-transparent bg-cable-avatar text-cable-avatar-foreground'
              : 'border-panel-border bg-bg-title text-content-secondary',
          )}
          role="presentation"
          aria-hidden="true"
          data-testid="avatar-fallback"
        >
          {initials ? (
            <svg
              className="size-full block text-current select-none"
              viewBox={`${-(50 + 22.5 * (initials.length - 1))} -50 ${100 + 45 * (initials.length - 1)} 100`}
              preserveAspectRatio="xMinYMid meet"
            >
              <text
                fontSize={55}
                fill="currentColor"
                textAnchor="middle"
                dominantBaseline="central"
              >
                {initials}
              </text>
            </svg>
          ) : (
            // Nothing to initialise from: a neutral person glyph beats an
            // empty coloured disc.
            <LucideUser className="h-1/2 w-1/2" />
          )}
        </AvatarFallback>
      </Avatar>
    );
  }),
);

RAGFlowAvatar.displayName = 'RAGFlowAvatar';

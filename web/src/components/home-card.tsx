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

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import { TruncatedText } from '@/components/truncated-text';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { formatDate } from '@/utils/date';
import { Clock3 } from 'lucide-react';
import { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

interface IProps {
  data: {
    name: string;
    description?: string;
    avatar?: string;
    update_time?: string | number;
    release_time?: number;
  };
  onClick?: () => void;
  moreDropdown: React.ReactNode;
  sharedBadge?: ReactNode;
  icon?: React.ReactNode;
  /**
   * Replaces the avatar block on the left of the card. Knowledge-base cards put
   * their class icon here instead of the first letter of the name.
   */
  leading?: ReactNode;
  /** Compact state marker, placed according to the selected card layout. */
  badge?: ReactNode;
  testId?: string;
  showReleaseTime?: boolean;
  /**
   * Secondary metadata slot. Agent cards place compact tags beside the summary;
   * other layouts may use it in their own metadata row.
   */
  extra?: ReactNode;
  /**
   * A rail of its own at the card's right edge, outside the text column, centred
   * in the card's height. For a card whose right edge has to carry content too —
   * a chat's message count, its model and the arrow that says the card opens —
   * rather than clamping a second thing into the title row.
   */
  trailing?: ReactNode;
  /** Visual-only class overrides for a specific card family. */
  className?: string;
  /** Uses structured layouts for agent, chat, memory and search cards. */
  layout?: 'standard' | 'agent' | 'chat' | 'memory' | 'search';
}

function Time({
  time,
  format,
  className,
}: {
  time: string | number | undefined;
  format?: string;
  className?: string;
}) {
  return (
    <p className={cn('truncate text-sm text-cable-muted', className)}>
      {formatDate(time, format)}
    </p>
  );
}

export function HomeCard({
  data,
  onClick,
  moreDropdown,
  sharedBadge,
  icon,
  leading,
  badge,
  testId,
  showReleaseTime = false,
  extra,
  trailing,
  className: cardClassName,
  layout = 'standard',
}: IProps) {
  const { t } = useTranslation();

  return (
    <Card
      as="article"
      data-testid={testId}
      data-agent-name={data.name}
      onClick={() => {
        // navigateToSearch(data?.id);
        onClick?.();
      }}
      tabIndex={0}
      className={cn(
        // `card-interactive` supplies the pointer cursor and the colour-only
        // hover tint. No transform or scale: these cards render inside
        // `overflow-hidden` grids, which clip a lifted card, so the lift comes
        // from the ceramic shadow rather than from a translate.
        // Standard cards use a single horizontal row; structured card families
        // arrange identity and metadata vertically within the same fixed height.
        // `h-[var(--list-card-height)]` + `overflow-hidden` is that contract — the
        // card never grows its row (a taller card would stretch every card beside
        // it), so every line below is truncated to one line and anything left over
        // is clipped. The height is a token because the page-size calculation
        // measures a region before any card has rendered and needs the same value.
        'card-interactive group flex h-[var(--list-card-height)] w-full overflow-hidden rounded-xl px-4 py-3',
        layout === 'agent'
          ? 'flex-col items-stretch justify-center gap-1'
          : layout === 'chat' || layout === 'memory'
            ? 'flex-col items-stretch justify-center gap-2'
            : layout === 'search'
              ? 'items-center justify-between gap-3'
              : 'items-center gap-3',
        // Translucent glass tint, so the page's own glow reads through the card
        // instead of stopping dead at an opaque surface. The ceramic shell adds
        // the inner rim light and the drop shadow, in whichever theme is active.
        'border border-cable-hairline bg-glass shadow-ceramic',
        'hover:border-ceramic-border-hover hover:shadow-ceramic-hover',
        // Needed because `Card` ships `transition-shadow`, which would otherwise
        // pin transition-property to box-shadow and drop the colour transition.
        // The ceramic hover moves the shadow too, so both are named here.
        'transition-[background-color,border-color,box-shadow,opacity] duration-200 ease-in-out',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cable-accent',
        cardClassName,
      )}
    >
      {layout === 'agent' ? (
        <>
          <div className="flex w-full min-w-0 items-center gap-3">
            <div className="flex size-8 shrink-0 items-center justify-center">
              {leading ?? (
                <RAGFlowAvatar
                  className="w-[32px] h-[32px]"
                  avatar={data.avatar}
                  name={data.name}
                />
              )}
            </div>

            <header className="flex min-w-0 flex-1 items-center gap-2">
              <TruncatedText
                as="h3"
                className="min-w-0 flex-1 truncate text-base font-bold leading-snug"
                testId="agent-name"
                tooltip={data.name}
              >
                {data.name}
              </TruncatedText>
              {icon}
              <div className="flex shrink-0 items-center">{moreDropdown}</div>
            </header>
          </div>

          <div className="flex w-full min-w-0 items-center gap-2">
            <TruncatedText
              className="min-w-0 flex-1 truncate text-xs leading-4 text-text-secondary"
              tooltip={data.description}
            >
              {data.description}
            </TruncatedText>
            {extra}
          </div>

          <div
            className="h-px w-full shrink-0 bg-cable-divider opacity-40"
            aria-hidden="true"
          />

          <div className="flex w-full min-w-0 items-center justify-between gap-2 rounded-md border border-cable-hairline bg-cable-surface/60 px-2 py-1">
            <div
              title={t('flow.lastSavedAt')}
              className="flex min-w-0 items-center gap-1.5"
            >
              <Clock3
                className="size-3 shrink-0 text-cable-muted"
                aria-hidden="true"
              />
              <Time
                time={data.update_time}
                format="DD/MM/YYYY HH:mm"
                className="text-[11px] leading-4"
              />
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {badge}
              {sharedBadge}
            </div>
          </div>
        </>
      ) : layout === 'memory' ? (
        <>
          <div className="flex w-full min-w-0 items-center gap-3">
            <div className="flex size-8 shrink-0 items-center justify-center">
              {leading ?? (
                <RAGFlowAvatar
                  className="w-[32px] h-[32px]"
                  avatar={data.avatar}
                  name={data.name}
                />
              )}
            </div>

            <header className="flex min-w-0 flex-1 items-center gap-2">
              <TruncatedText
                as="h3"
                className="min-w-0 flex-1 truncate text-sm font-bold leading-snug"
                testId="agent-name"
                tooltip={data.name}
              >
                {data.name}
              </TruncatedText>
              {icon}
              <div className="flex shrink-0 items-center gap-1">
                {badge}
                {moreDropdown}
              </div>
            </header>
          </div>

          <div
            className="h-px w-full shrink-0 bg-cable-divider opacity-40"
            aria-hidden="true"
          />

          <div className="flex w-full min-w-0 items-center justify-between gap-2 pt-1">
            <Time
              time={data.update_time}
              format="DD/MM/YYYY HH:mm"
              className="text-xs"
            />
            <div className="flex min-w-0 items-center gap-2">
              {extra}
              {sharedBadge}
            </div>
          </div>
        </>
      ) : layout === 'search' ? (
        <>
          <div className="flex min-w-0 flex-[0_1_48%] flex-col justify-center gap-2">
            <header className="flex min-w-0 items-center gap-2">
              <div className="flex size-8 shrink-0 items-center justify-center">
                {leading ?? (
                  <RAGFlowAvatar
                    className="w-[32px] h-[32px]"
                    avatar={data.avatar}
                    name={data.name}
                  />
                )}
              </div>
              <TruncatedText
                as="h3"
                className="min-w-0 flex-1 truncate text-sm font-bold leading-snug"
                testId="agent-name"
                tooltip={data.name}
              >
                {data.name}
              </TruncatedText>
              <div className="flex shrink-0 items-center">{moreDropdown}</div>
            </header>
            <Time
              time={data.update_time}
              format="DD/MM/YYYY HH:mm"
              className="text-xs"
            />
          </div>
          <div className="flex min-w-0 flex-[1_1_52%] items-center">
            {trailing}
          </div>
        </>
      ) : layout === 'chat' ? (
        <>
          <div className="flex w-full min-w-0 items-center gap-3">
            <div className="flex size-8 shrink-0 items-center justify-center">
              {leading ?? (
                <RAGFlowAvatar
                  className="w-[32px] h-[32px]"
                  avatar={data.avatar}
                  name={data.name}
                />
              )}
            </div>

            <header className="flex min-w-0 flex-1 items-center gap-2">
              <TruncatedText
                as="h3"
                className="min-w-0 flex-1 truncate text-base font-bold leading-snug"
                testId="agent-name"
                tooltip={data.name}
              >
                {data.name}
              </TruncatedText>

              {icon}

              <div className="flex shrink-0 items-center gap-1">
                {badge}
                {moreDropdown}
              </div>
            </header>
          </div>

          <div
            className="h-px w-full shrink-0 bg-cable-divider opacity-60"
            aria-hidden="true"
          />

          <div className="flex w-full min-w-0 items-center justify-between gap-2 pt-1">
            <Time
              time={data.update_time}
              format="DD/MM/YYYY HH:mm"
              className="text-xs"
            />
            {trailing}
          </div>
        </>
      ) : (
        <>
          <div className="flex size-8 shrink-0 items-center justify-center">
            {leading ?? (
              <RAGFlowAvatar
                className="w-[32px] h-[32px]"
                avatar={data.avatar}
                name={data.name}
              />
            )}
          </div>

          <div className="flex min-w-0 flex-1 flex-col justify-center gap-1">
            <header className="flex min-w-0 flex-row items-center gap-2">
              <TruncatedText
                as="h3"
                className="min-w-0 flex-1 truncate text-base font-bold leading-snug"
                testId="agent-name"
                tooltip={data.name}
              >
                {data.name}
              </TruncatedText>

              {extra}
              {icon}

              <div className="flex shrink-0 items-center gap-1">
                {badge}
                {moreDropdown}
              </div>
            </header>

            <TruncatedText
              className="text-sm leading-5 whitespace-nowrap overflow-hidden text-ellipsis"
              tooltip={data.description}
            >
              {data.description}
            </TruncatedText>

            <div className="flex justify-between items-center gap-2 min-w-0">
              {showReleaseTime ? (
                <section className="flex min-w-0 items-center gap-2 text-sm text-text-secondary">
                  <span className="truncate whitespace-nowrap">
                    {t('flow.lastSavedAt')}:
                  </span>
                  <Time time={data.update_time}></Time>
                  {data.release_time && (
                    <>
                      <span className="truncate whitespace-nowrap">
                        {t('flow.publishedAt')}:
                      </span>
                      <Time time={data.release_time}></Time>
                    </>
                  )}
                </section>
              ) : (
                <Time time={data.update_time}></Time>
              )}
              {sharedBadge}
            </div>
          </div>

          {trailing}
        </>
      )}
    </Card>
  );
}

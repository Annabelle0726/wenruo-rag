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

import { cn } from '@/lib/utils';
import { t } from 'i18next';
import { useIsDarkTheme } from '../theme-provider';

import { Plus } from 'lucide-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import SvgIcon from '../svg-icon';
import { EmptyCardData, EmptyCardType, EmptyType } from './constant';
import { EmptyCardProps, EmptyProps } from './interface';

const EmptyIcon = ({ name, width }: { name: string; width?: number }) => {
  return <SvgIcon name={name || 'empty/no-data-dark'} width={width || 42} />;
};

const Empty = (props: EmptyProps) => {
  const { className, children, type, text, iconWidth } = props;
  const isDarkTheme = useIsDarkTheme();

  const name = useMemo(() => {
    return isDarkTheme
      ? `empty/no-${type || EmptyType.Data}-dark`
      : `empty/no-${type || EmptyType.Data}-bri`;
  }, [isDarkTheme, type]);

  return (
    <div
      className={cn(
        'flex flex-col justify-center items-center text-center gap-2',
        className,
      )}
    >
      <EmptyIcon name={name} width={iconWidth} />

      {!children && (
        <div className="empty-text text-text-secondary text-sm">
          {text ||
            (type === 'data' ? t('common.noData') : t('common.noResults'))}
        </div>
      )}
      {children}
    </div>
  );
};

export default Empty;

export const EmptyCard = (props: EmptyCardProps) => {
  const { icon, className, children, title, description, ...restProps } = props;
  return (
    <article
      className={cn(
        // The same footprint as the cards it stands in for: exactly the card's
        // 112px so a grid holding nothing but this tile shows a card-sized slot,
        // and a centred row for the icon, the plus and the prompt.
        'flex h-[112px] min-h-[112px] w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border border-dashed border-border-button px-4 py-4 text-center',
        className,
      )}
      {...restProps}
    >
      {(icon || title) && (
        <div className="flex flex-row flex-wrap items-center justify-center gap-2">
          {icon}
          {title && (
            <span className="text-sm text-text-primary">{title}</span>
          )}
        </div>
      )}
      {description && (
        <p className="text-sm text-text-secondary">{description}</p>
      )}
      {children}
    </article>
  );
};

export const EmptyAppCard = (props: {
  type: EmptyCardType;
  onClick?: () => void;
  showIcon?: boolean;
  className?: string;
  isSearch?: boolean;
  children?: React.ReactNode;
  testId?: string;
  tabIndex?: number;
}) => {
  const { type, showIcon, className, isSearch, children, testId, tabIndex } =
    props;
  const { t } = useTranslation();
  const cardData = EmptyCardData[type];
  // The create tile states what the click does, and the "nothing matched" state
  // says what came back empty — one line either way, next to the icons.
  const title = t(cardData.titleKey);
  const notFound = t(cardData.notFoundKey);

  return (
    // `w-full` with no inset or size override of its own, so the tile is a grid
    // item exactly like the cards around it: same column width, same row height.
    <div className="flex w-full justify-center">
      <EmptyCard
        onClick={isSearch ? undefined : props.onClick}
        data-testid={testId}
        tabIndex={tabIndex ?? (isSearch ? undefined : 0)}
        icon={isSearch && showIcon ? cardData.icon : undefined}
        title={isSearch ? notFound : undefined}
        className={cn(
          // The tile is a button: the pointer cursor, a theme-blue hairline and
          // one soft accent glow on hover. No lift and no scale, so the
          // surrounding grid never clips it.
          !isSearch &&
            'card-interactive transition-[background-color,border-color,box-shadow] duration-200 ease-in-out hover:border-accent-color hover:shadow-accent-glow',
          className,
        )}
      >
        {!isSearch && !children && (
          // Icon, plus and prompt as one horizontal group in the middle of the
          // tile: they used to be stacked, which left the plus above the text.
          <div className="flex flex-row flex-wrap items-center justify-center gap-2">
            {showIcon && cardData.icon}
            <Plus size={24} />
            <span className="text-sm text-text-secondary">{title}</span>
          </div>
        )}
        {children}
      </EmptyCard>
    </div>
  );
};

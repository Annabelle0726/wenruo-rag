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
import { Funnel } from 'lucide-react';
import React, {
  ChangeEventHandler,
  PropsWithChildren,
  ReactNode,
  useMemo,
} from 'react';
import { HomeIcon } from '../svg-icon';
import { Button, ButtonProps } from '../ui/button';
import { SearchInput } from '../ui/input';
import { CheckboxFormMultipleProps, FilterPopover } from './filter-popover';

interface IProps {
  title?: ReactNode;
  searchString?: string;
  onSearchChange?: ChangeEventHandler<HTMLInputElement>;
  showFilter?: boolean;
  showSearch?: boolean;
  leftPanel?: ReactNode;
  preChildren?: ReactNode;
}

export const FilterButton = React.forwardRef<
  HTMLButtonElement,
  ButtonProps & { count?: number }
>(({ count = 0, ...props }, ref) => {
  return (
    <Button
      // Flat 32px control on the same rail as the search field and the page's
      // create button: 1px hairline, 2px corners, no elevation.
      //
      // `ghost`, not the default variant: the default one is an ink-filled
      // button, so it would put `bg-text-primary` on this control and flip it
      // to a near-black `hover:bg-text-primary/90` under the pointer — a
      // `:hover` utility outranks `.ceramic-relief`, which is why the wash was
      // painting over the flat surface.
      variant="ghost"
      className={cn(
        'ceramic-relief h-8 shrink-0 rounded-[2px] text-text-secondary hover:bg-surface-hover hover:text-cable-brand focus-visible:bg-surface-hover focus-visible:text-cable-brand transition-colors',
        count > 0 ? 'px-3' : 'w-8 px-0',
      )}
      size="auto"
      {...props}
      ref={ref}
    >
      <Funnel />

      {count > 0 && (
        <span className="rounded-[2px] bg-bg-title px-1 py-0.5 text-xs leading-none text-text-primary">
          {count}
        </span>
      )}
    </Button>
  );
});

FilterButton.displayName = 'FilterButton';

/**
 * The flat search field, shared by the bar and by the pages that render their
 * own box (skills hides the bar's search). It is the 1px-bordered half of the
 * panel, on the same 32px rail as the controls around it.
 *
 * The inset for the text lives on the prefix `span`, not on the input: `Input`
 * measures that span and writes its width into an inline `padding-inline-start`,
 * which no padding class can override. Padding the span therefore moves the
 * magnifier in *and* moves the text past it, which is what keeps the placeholder
 * from starting under the icon.
 */
export const ceramicSearchFieldClassName =
  'ceramic-well h-8 w-full rounded-[2px] px-3 placeholder:text-content-secondary';

export const ceramicSearchFieldRootClassName =
  '[&>span]:ps-2.5 [&>span>svg]:ms-0 [&>span>svg]:me-1.5 [&>span]:text-content-secondary';

export default function ListFilterBar({
  title,
  children,
  preChildren,
  searchString,
  onSearchChange,
  showFilter = true,
  showSearch = true,
  leftPanel,
  value,
  onChange,
  onOpenChange,
  filters,
  className,
  icon,
  iconClassName,
  filterGroup,
  searchVariant = 'capsule',
}: PropsWithChildren<IProps & Omit<CheckboxFormMultipleProps, 'setOpen'>> & {
  className?: string;
  icon?: ReactNode;
  iconClassName?: string;
  filterGroup?: Record<string, string[]>;
  /**
   * `capsule` is the ceramic field every list page shows: the recessed surface,
   * the shared hairline, an accent ring on focus and the magnifier inked in the
   * secondary content colour. It is the default so a new page cannot land on a
   * field of a different height; `default` keeps the primitive's plain box for
   * callers that are not part of a list toolbar.
   */
  searchVariant?: 'default' | 'capsule';
}) {
  const filterCount = useMemo(() => {
    return typeof value === 'object' && value !== null
      ? Object.values(value).reduce((pre, cur) => {
          if (Array.isArray(cur)) {
            return pre + cur.length;
          }
          if (typeof cur === 'object') {
            return (
              pre +
              Object.values(cur).reduce((pre, cur) => {
                return pre + (cur?.length || 0);
              }, 0)
            );
          }
          return pre;
        }, 0)
      : 0;
  }, [value]);

  const hasFilter = Boolean(filters?.length && showFilter);

  return (
    <div
      className={cn(
        'flex min-w-0 flex-col gap-3 md:flex-row md:items-center md:justify-between',
        className,
      )}
    >
      <h1 className="flex min-w-0 shrink-0 items-center gap-2 text-base font-semibold">
        {typeof icon === 'string' ? (
          <HomeIcon
            name={`${icon}`}
            imgClass={cn('size-[1em] text-cable-brand', iconClassName)}
          />
        ) : (
          icon
        )}
        {leftPanel || title}
      </h1>

      <div
        className={cn(
          // One control row on every list page: centred on the 32px rail and
          // pushed to the right edge, so switching pages never moves the create
          // button sideways or up.
          'min-w-0 w-full items-center gap-2',
          preChildren
            ? 'flex flex-wrap md:flex-nowrap md:w-auto md:shrink-0 md:justify-end'
            : cn(
                'grid',
                hasFilter
                  ? 'grid-cols-[auto_minmax(0,1fr)_auto]'
                  : 'grid-cols-[minmax(0,1fr)_auto]',
                'md:flex md:w-auto md:shrink-0 md:justify-end',
              ),
        )}
        role="toolbar"
      >
        {preChildren}
        {hasFilter && (
          <FilterPopover
            value={value}
            onChange={onChange}
            filters={filters}
            filterGroup={filterGroup}
            onOpenChange={onOpenChange}
          >
            <FilterButton count={filterCount} />
          </FilterPopover>
        )}
        {showSearch && (
          <SearchInput
            value={searchString}
            onChange={onSearchChange}
            className={cn(
              'min-w-0',
              preChildren ? 'flex-1 basis-32' : '',
              'md:w-32',
              searchVariant === 'capsule' && ceramicSearchFieldClassName,
            )}
            rootClassName={cn(
              // A little more air before the create action: on the bare 12px
              // rhythm the field and the pill read as one control, and the field
              // sits a touch left of where the eye expects it.
              'me-2',
              searchVariant === 'capsule' && ceramicSearchFieldRootClassName,
            )}
            role="searchbox"
          />
        )}

        {children && (
          <div className="shrink-0 justify-self-end">{children}</div>
        )}
      </div>
    </div>
  );
}

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
import { supportsCssAnchor } from '@/utils/css-support';
import { MouseEventHandler, ReactNode, useCallback, useId } from 'react';

export type CeramicSegmentedValue = string | number;

export type CeramicSegmentedOption = {
  value: CeramicSegmentedValue;
  label: ReactNode;
};

type CeramicSegmentedProps = {
  options: CeramicSegmentedOption[];
  value?: CeramicSegmentedValue;
  onChange?: (value: CeramicSegmentedValue) => void;
  className?: string;
};

/**
 * Segmented control in the navigation bar's ceramic material.
 *
 * `components/ui/segmented` cannot be used for this: its sliding highlight keeps
 * a fixed square-ish radius and surface of its own on the element itself, and the
 * only per-item hook it exposes is shared between the tabs and that highlight, so
 * a capsule tab cannot be expressed through it. This component renders the same
 * behaviour against the ceramic tokens instead — a recessed capsule holding one
 * raised tab — and is meant for the surface-level switchers on the home page.
 *
 * The raised tab is a separate element positioned over the selected button by CSS
 * anchor positioning, exactly like the navigation capsule, so switching tabs
 * slides it rather than repainting each button.
 */
export function CeramicSegmented({
  options,
  value,
  onChange,
  className,
}: CeramicSegmentedProps) {
  const anchorNamePrefix = useId().replace(/:/g, '');
  const activeIndex = options.findIndex((option) => option.value === value);

  // One handler for every tab: an inline arrow per option would be recreated on
  // each render and would break memoisation of the rows above.
  const handleSelect: MouseEventHandler<HTMLButtonElement> = useCallback(
    (event) => {
      const selected = options.find(
        (option) => String(option.value) === event.currentTarget.dataset.value,
      );

      if (selected) {
        onChange?.(selected.value);
      }
    },
    [onChange, options],
  );

  return (
    <div
      role="group"
      className={cn(
        'ceramic-segmented flex items-center gap-1 rounded-full p-1',
        className,
      )}
    >
      {options.map((option, index) => {
        const isSelected = option.value === value;

        return (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={isSelected}
            data-testid={`ceramic-segment-${String(option.value)}`}
            data-value={String(option.value)}
            onClick={handleSelect}
            // Without anchor positioning there is no separate highlight to slide,
            // so the selected tab wears the ceramic pill itself.
            className={cn(
              'relative z-10 inline-flex h-8 items-center justify-center whitespace-nowrap rounded-full px-3.5 text-sm',
              // The selected label carries the brand colour and a touch more
              // weight: on the plain white tab the text is the only thing left to
              // say which tab is current.
              isSelected
                ? 'font-medium text-accent-color'
                : 'ceramic-segment-idle text-cable-nav hover:text-cable-nav-text-hover',
              isSelected && !supportsCssAnchor && 'ceramic-segment-pill',
            )}
            style={{ anchorName: `--${anchorNamePrefix}-${index}` }}
          >
            {/* The label is measured twice: the invisible copy is set at the
                selected weight so the button's width never changes when a tab
                becomes current, and the visible copy is painted over it. Without
                the reservation a font that spaces its medium weight differently
                would resize the button, shifting every tab after it and the pill
                with them — the click itself would look like a jitter. */}
            <span className="relative inline-flex items-center justify-center">
              <span aria-hidden className="invisible font-medium">
                {option.label}
              </span>
              <span className="absolute inset-0 inline-flex items-center justify-center">
                {option.label}
              </span>
            </span>
          </button>
        );
      })}

      {supportsCssAnchor && (
        <span
          // Decoration only: the buttons carry the label and the pressed state.
          aria-hidden
          data-testid="ceramic-segment-pill"
          className={cn(
            'ceramic-segment-pill absolute',
            activeIndex < 0 && 'opacity-0',
          )}
          style={{
            positionAnchor: `--${anchorNamePrefix}-${activeIndex}`,
            width: 'anchor-size(width)',
            height: 'anchor-size(height)',
            top: 'anchor(top)',
            left: 'anchor(left)',
          }}
        />
      )}
    </div>
  );
}

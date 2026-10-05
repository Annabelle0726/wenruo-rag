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

import { useIsDarkTheme, useTheme } from '@/components/theme-provider';
import { ThemeEnum } from '@/constants/common';
import { cn } from '@/lib/utils';
import { Root, Thumb } from '@radix-ui/react-switch';
import { LucideMoon, LucideSun } from 'lucide-react';
import { forwardRef } from 'react';

const ThemeSwitch = forwardRef<
  React.ElementRef<typeof Root>,
  React.ComponentPropsWithoutRef<typeof Root>
>(function ThemeSwitch({ className, ...props }, ref) {
  const { setTheme } = useTheme();
  const isDark = useIsDarkTheme();

  /**
   * The selected icon sits on the brand slider, so it takes the ink that reads on
   * the accent; the other one keeps the secondary text colour and brightens under
   * the pointer. No bloom: the 国网 skin moves state with colour alone.
   */
  const iconClass = (isSelected: boolean) =>
    cn(
      'size-[1em] transition-colors duration-300 ease-in-out',
      isSelected
        ? 'text-accent-contrast'
        : 'text-text-secondary group-hover/theme-switch:text-text-primary',
    );

  return (
    <Root
      ref={ref}
      className={cn(
        // Ceramic tray: a glass recess with the hairline edge, held down onto the
        // footer by a tight contact shadow and the accent ring on focus.
        'ceramic-switch group/theme-switch relative rounded-full outline-none self-center',
        'focus-visible:ring-2 focus-visible:ring-accent-color-soft',
        className,
      )}
      {...props}
      checked={isDark}
      onCheckedChange={(value) =>
        setTheme(value ? ThemeEnum.Dark : ThemeEnum.Light)
      }
    >
      <div className="self-center rounded-full px-2.5 py-1.5 transition-colors duration-300 ease-in-out">
        <div className="relative z-[1] flex h-full items-center justify-between gap-3">
          <LucideSun className={iconClass(!isDark)} />
          <LucideMoon className={iconClass(isDark)} />
        </div>
      </div>

      <Thumb
        className={cn(
          'absolute top-0 left-0 w-[calc(50%+.25rem)] p-0.5 h-full rounded-full overflow-hidden',
          'transition-all duration-300 ease-in-out',
          'group-hover/theme-switch:w-[calc(50%+.66rem)] group-focus-visible/theme-switch:w-[calc(50%+.66rem)]',
          {
            'left-[calc(50%-.25rem)] group-hover/theme-switch:left-[calc(50%-.66rem)] group-focus-visible/theme-switch:left-[calc(50%-.66rem)]':
              isDark,
          },
        )}
      >
        <div className="ceramic-switch-thumb size-full rounded-full" />
      </Thumb>
    </Root>
  );
});

export default ThemeSwitch;

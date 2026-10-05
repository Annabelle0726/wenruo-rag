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

'use client';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { LucideX } from 'lucide-react';
import { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

type SettingsDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Selector root: the panel is `${testId}`, its body `${testId}-body` and its
   * close button `${testId}-close`. */
  testId: string;
  /** Action row pinned below the scroll area, e.g. cancel and save. */
  footer?: ReactNode;
  /**
   * Anchor the drawer to the element it is rendered in instead of the viewport.
   * The search page uses this so the panel and its backdrop start at the app
   * bar's bottom edge and leave the bar itself alone; the default keeps the
   * viewport anchoring the chat page relies on, where the drawer covers the
   * page's own header.
   */
  contained?: boolean;
  children: ReactNode;
};

/**
 * Right-hand slide-over shared by the chat and search settings.
 *
 * Built on the Radix dialog primitive rather than `components/ui/sheet.tsx`:
 * that shared sheet hard-codes an 80%-black overlay and a one-third-width panel,
 * while this drawer needs a light backdrop that leaves the page readable, a
 * fixed 480px rail, and its own scroll container. It is taken out of the page
 * flow, so opening it never reflows or covers the content's own scrollbar — the
 * drawer scrolls, the page underneath does not move.
 */
export function SettingsDrawer({
  open,
  onOpenChange,
  title,
  testId,
  footer,
  contained = false,
  children,
}: SettingsDrawerProps) {
  const { t } = useTranslation();

  const content = (
    <>
      <DialogPrimitive.Overlay
        className={cn(
          'inset-0 z-40 bg-cable-backdrop',
          'data-[state=open]:animate-in data-[state=open]:fade-in-0',
          'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          'data-[state=closed]:pointer-events-none',
          contained ? 'absolute' : 'fixed',
        )}
      />
      <DialogPrimitive.Content
        // Radix warns when a dialog has no description; the title alone says
        // everything this panel needs to.
        aria-describedby={undefined}
        className={cn(
          'glass-panel inset-y-0 right-0 z-50 flex w-full max-w-[80vw] flex-col',
          'shadow-cable-drawer outline-none',
          'transition ease-in-out',
          'data-[state=open]:animate-in data-[state=open]:slide-in-from-right data-[state=open]:duration-300',
          'data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=closed]:duration-200',
          'data-[state=closed]:pointer-events-none',
          'sm:w-[480px]',
          contained ? 'absolute' : 'fixed',
        )}
        data-testid={testId}
      >
        <header className="flex shrink-0 items-center justify-between gap-4 border-b border-cable-hairline px-5 py-4">
          <DialogPrimitive.Title className="text-base font-medium text-text-primary">
            {title}
          </DialogPrimitive.Title>

          <DialogPrimitive.Close asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="rounded-lg text-text-secondary hover:bg-cable-brand-soft hover:text-cable-brand"
              aria-label={t('common.close', 'Close')}
              data-testid={`${testId}-close`}
            >
              <LucideX className="size-4" />
            </Button>
          </DialogPrimitive.Close>
        </header>

        {/* The drawer body is the only scroll container: every setting stays
            reachable on a short viewport without squeezing the fields. */}
        <div
          className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
          data-testid={`${testId}-body`}
        >
          {children}
        </div>

        {footer && (
          <footer className="shrink-0 border-t border-cable-hairline px-5 py-3">
            {footer}
          </footer>
        )}
      </DialogPrimitive.Content>
    </>
  );

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      {contained ? content : <DialogPrimitive.Portal>{content}</DialogPrimitive.Portal>}
    </DialogPrimitive.Root>
  );
}

import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { BrandLockup } from './brand-lockup';

/**
 * System bottom bar: the page's closing edge, not a stray line of legal text.
 *
 * Three levels of information, in one row on a wide viewport and stacked on a
 * narrow one — the brand name, the product it belongs to, and the copyright — so
 * the eye has an order to follow and the bar reads as the same institution as the
 * header. It states only what the product already states elsewhere (the brand
 * name, the product name from the header, the copyright): no version, no build
 * stamp, no system status and no qualification is invented here.
 *
 * The surface is the page canvas closing itself, never a panel: `.shell-footer`
 * paints a 3.5% gradient that starts transparent plus a hairline whose ends fade
 * out, so the workspace flows into the bottom edge instead of meeting a block
 * (and in dark mode there is no bright rectangle under a dark page). The rhythm
 * stays minimal — 16px above and below the stacked form, 14px on the wide one.
 *
 * `mt-auto` pins it to the bottom of a flex column page (`pages/home`) and is
 * inert everywhere else, so a short page is still closed by the same edge. It is
 * a normal flow element — never fixed, never sticky — so it cannot cover page
 * content, and it adds no scroll of its own: it is shorter than the footer it
 * replaces (a 64px bar against the 80px block it was).
 */
export function AppFooter({
  className,
  variant = 'default',
}: {
  className?: string;
  variant?: 'default' | 'login';
}) {
  const { t } = useTranslation();

  return (
    <footer className={cn('shell-footer mt-auto w-full shrink-0', className)}>
      <div className="page-gutter flex flex-col items-start gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8 sm:py-3.5">
        {/* 第一、二层信息：品牌名与它所属的产品 */}
        <div className="flex min-w-0 items-center gap-2.5">
          <BrandLockup />
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[13px] font-semibold text-text-primary">
              {t('header.brandShort')}
            </p>
            <p className="truncate text-xs text-content-tertiary">
              {t('header.heroTitle')}
            </p>
          </div>
        </div>

        {/* 右侧法律信息；登录页附带备案号占位，其他页面维持原文案 */}
        <div className="flex min-w-0 items-center gap-4">
          <span
            aria-hidden
            className="hidden h-9 w-px shrink-0 bg-panel-border md:block"
          />
          {variant === 'login' ? (
            <div className="min-w-0 space-y-1 text-xs text-content-secondary sm:text-right">
              <p>{t('footer.loginCopyright')}</p>
              <p className="text-content-tertiary">
                {t('footer.icpPlaceholder')}
              </p>
            </div>
          ) : (
            <p className="min-w-0 text-xs text-content-secondary sm:text-right">
              {t('footer.copyright')}
            </p>
          )}
        </div>
      </div>
    </footer>
  );
}

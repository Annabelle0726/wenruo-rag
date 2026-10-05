import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  DatasetCategoryDefinitions,
  DatasetCategoryNavOrder,
} from '@/constants/dataset-category';
import { cn } from '@/lib/utils';
import { DatePicker } from '@/components/ui/date-picker';
import { RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { AllDatasetCategories, DatasetQuery } from './use-dataset-query';

/** Every control in the panel sits on the same 32px rail. */
const controlClass =
  'h-8 rounded-[2px] border border-panel-border bg-bg-component text-sm shadow-none focus-visible:ring-0';

const fieldLabelClass = 'mb-1 block text-xs text-content-secondary';

function Field({
  label,
  children,
  className,
}: React.PropsWithChildren<{ label: string; className?: string }>) {
  return (
    <div className={cn('flex flex-col', className)}>
      <span className={fieldLabelClass}>{label}</span>
      {children}
    </div>
  );
}

export type DatasetQueryPanelProps = {
  query: DatasetQuery;
  onCategoryChange: (category: string) => void;
  onKeywordChange: (keyword: string) => void;
  onCreatedFromChange: (date?: Date) => void;
  onCreatedToChange: (date?: Date) => void;
  onReset: () => void;
  className?: string;
};

/**
 * 工业级「查询条件」面板。方形白底卡片 + 1px 实线边框，条件在同一行内横向排开：
 * 文件分类 / 关键词检索 / 创建时间范围。控件一律 32px 高、2px 直角，右侧只保留
 * 一个 重置 文本按钮——筛选是即时的，再放一个「查询」按钮只会是空动作。
 */
export function DatasetQueryPanel({
  query,
  onCategoryChange,
  onKeywordChange,
  onCreatedFromChange,
  onCreatedToChange,
  onReset,
  className,
}: DatasetQueryPanelProps) {
  const { t } = useTranslation();

  return (
    <section
      aria-label={t('datasetTable.queryPanel')}
      className={cn(
        'flex flex-wrap items-end gap-x-4 gap-y-3 border border-panel-border bg-bg-component px-4 py-3',
        className,
      )}
      data-testid="dataset-query-panel"
    >
      <Field label={t('datasetTable.category')} className="w-[180px]">
        <Select value={query.category} onValueChange={onCategoryChange}>
          <SelectTrigger
            className={cn(
              controlClass,
              'text-text-primary hover:bg-bg-component hover:text-text-primary',
            )}
            data-testid="dataset-query-category"
          >
            <SelectValue placeholder={t('datasetTable.allCategories')} />
          </SelectTrigger>
          <SelectContent className="border-panel-border">
            <SelectItem value={AllDatasetCategories}>
              {t('datasetTable.allCategories')}
            </SelectItem>
            {DatasetCategoryNavOrder.map((category) => (
              <SelectItem key={category} value={category}>
                {t(DatasetCategoryDefinitions[category].labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label={t('datasetTable.keyword')} className="w-[240px]">
        <Input
          value={query.keyword}
          onChange={(e) => onKeywordChange(e.target.value)}
          placeholder={t('datasetTable.keywordPlaceholder')}
          className={cn(
            controlClass,
            'px-2.5 py-1 text-text-primary hover:border-cable-brand',
          )}
          data-testid="dataset-query-keyword"
        />
      </Field>

      <Field label={t('datasetTable.createdRange')}>
        <div className="flex items-center gap-2">
          <DatePicker
            value={query.createdFrom}
            onChange={onCreatedFromChange}
            dateFormat="YYYY-MM-DD"
            placeholder={t('datasetTable.datePlaceholder')}
            className={cn(controlClass, 'w-[150px] px-2.5 py-1')}
            data-testid="dataset-query-created-from"
          />
          <span className="text-xs text-text-disabled">
            {t('datasetTable.rangeSeparator')}
          </span>
          <DatePicker
            value={query.createdTo}
            onChange={onCreatedToChange}
            dateFormat="YYYY-MM-DD"
            placeholder={t('datasetTable.datePlaceholder')}
            className={cn(controlClass, 'w-[150px] px-2.5 py-1')}
            data-testid="dataset-query-created-to"
          />
        </div>
      </Field>

      <button
        type="button"
        onClick={onReset}
        className="mb-0.5 inline-flex h-8 items-center gap-1 border border-panel-border px-3 text-sm text-content-secondary transition-colors hover:border-cable-brand hover:text-cable-brand"
        data-testid="dataset-query-reset"
      >
        <RotateCcw className="size-3.5" />
        {t('datasetTable.reset')}
      </button>
    </section>
  );
}

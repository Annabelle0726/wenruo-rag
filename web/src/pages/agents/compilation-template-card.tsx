import { MoreButton } from '@/components/more-button';
import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import { TruncatedText } from '@/components/truncated-text';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ICompilationTemplateGroup } from '@/interfaces/database/compilation-template';
import { formatDate } from '@/utils/date';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { formatKindLabel } from '@/utils/compilation-template-util';
import { CompilationTemplateDropdown } from './compilation-template-dropdown';
import { FlowType, FlowTypeConfig } from './constant';

type CompilationTemplateCardProps = {
  data: ICompilationTemplateGroup;
  onClick?: () => void;
  onDelete?: (id: string) => void;
};

const CompilerConfig = FlowTypeConfig[FlowType.Compiler];
const CompilerIcon = CompilerConfig.icon;

export function CompilationTemplateCard({
  data,
  onClick,
  onDelete,
}: CompilationTemplateCardProps) {
  const { t } = useTranslation();
  const kinds = useMemo(
    () => Array.from(new Set((data.templates ?? []).map((item) => item.kind))),
    [data.templates],
  );

  return (
    <Card
      // The same fixed card as the agent card it shares the grid with: the badge
      // row and the date share one line instead of stacking, which is what keeps
      // a template group from standing taller than everything beside it.
      className="card-interactive group h-[112px] overflow-hidden bg-glass border border-cable-hairline shadow-ceramic hover:border-ceramic-border-hover hover:shadow-ceramic-hover transition-[background-color,border-color,box-shadow,opacity] duration-200 ease-in-out"
      onClick={onClick}
    >
      <CardContent className="py-3 px-2.5 flex h-full gap-3 items-center">
        <RAGFlowAvatar
          avatar={data.avatar}
          name={data.name}
          className="w-8 h-8 shrink-0"
        />

        <div className="flex-1 min-w-0 flex flex-col gap-1">
          <section className="flex items-center justify-between gap-2">
            <TruncatedText
              as="h3"
              className="flex-1 min-w-0 truncate text-base font-bold leading-snug"
              tooltip={data.name}
            >
              {data.name}
            </TruncatedText>

            <Button variant="ghost" size="sm">
              <CompilerIcon style={{ color: CompilerConfig.color }} />
            </Button>

            {onDelete && (
              <CompilationTemplateDropdown data={data} onDelete={onDelete}>
                <MoreButton />
              </CompilationTemplateDropdown>
            )}
          </section>

          <TruncatedText
            as="p"
            className="text-sm text-text-secondary line-clamp-1"
            tooltip={data.description}
          >
            {data.description}
          </TruncatedText>

          <div className="flex items-center justify-between gap-2 min-w-0 text-sm text-text-secondary">
            {/* Same shape as the app cards: the date on the left, the kind badges
                on the right, clamped to the one line the card has for them. */}
            <section className="flex min-w-0 items-center gap-2">
              <span className="truncate whitespace-nowrap">
                {t('flow.lastSavedAt')}:
              </span>
              <p className="truncate">{formatDate(data.update_time)}</p>
            </section>

            <div className="flex min-w-0 shrink flex-nowrap gap-1 overflow-hidden">
              {kinds.map((kind) => (
                <Badge key={kind} variant="secondary" className="shrink-0">
                  {formatKindLabel(t, kind)}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

import { useFormContext, useWatch } from 'react-hook-form';

import { DocumentParserType } from '@/constants/knowledge';
import { useMemo } from 'react';
import { AudioConfiguration } from './configuration/audio';
import { BookConfiguration } from './configuration/book';
import { EmailConfiguration } from './configuration/email';
import { KnowledgeGraphConfiguration } from './configuration/knowledge-graph';
import { LawsConfiguration } from './configuration/laws';
import { ManualConfiguration } from './configuration/manual';
import { NaiveConfiguration } from './configuration/naive';
import { OneConfiguration } from './configuration/one';
import { PaperConfiguration } from './configuration/paper';
import { PictureConfiguration } from './configuration/picture';
import { PresentationConfiguration } from './configuration/presentation';
import { QAConfiguration } from './configuration/qa';
import { ResumeConfiguration } from './configuration/resume';
import { TableConfiguration } from './configuration/table';
import { TagConfiguration } from './configuration/tag';

const ConfigurationComponentMap = {
  [DocumentParserType.Naive]: NaiveConfiguration,
  [DocumentParserType.Qa]: QAConfiguration,
  [DocumentParserType.Resume]: ResumeConfiguration,
  [DocumentParserType.Manual]: ManualConfiguration,
  [DocumentParserType.Table]: TableConfiguration,
  [DocumentParserType.Paper]: PaperConfiguration,
  [DocumentParserType.Book]: BookConfiguration,
  [DocumentParserType.Laws]: LawsConfiguration,
  [DocumentParserType.Presentation]: PresentationConfiguration,
  [DocumentParserType.Picture]: PictureConfiguration,
  [DocumentParserType.One]: OneConfiguration,
  [DocumentParserType.Audio]: AudioConfiguration,
  [DocumentParserType.Email]: EmailConfiguration,
  [DocumentParserType.Tag]: TagConfiguration,
  [DocumentParserType.KnowledgeGraph]: KnowledgeGraphConfiguration,
};

function EmptyComponent() {
  return <div></div>;
}

/**
 * The selected built-in parser's own sections.
 *
 * It renders them straight into the page's stack of section cards. It used to wrap
 * them in a second `overflow-auto` box, which the page no longer needs - and must
 * not have: the page's field area is the one scroll region under the header, and a
 * scroller inside it would put two scrollbars in the same column (the outer one with
 * nothing to scroll, the inner one carrying the whole form).
 */
export function ChunkMethodForm() {
  const form = useFormContext();

  const finalParserId: DocumentParserType = useWatch({
    control: form.control,
    name: 'chunk_method',
  });

  const ConfigurationComponent = useMemo(() => {
    return finalParserId
      ? ConfigurationComponentMap[finalParserId]
      : EmptyComponent;
  }, [finalParserId]);

  return <ConfigurationComponent></ConfigurationComponent>;
}

import { Modal } from '@/components/ui/modal/modal';
import { useSetModalState } from '@/hooks/common-hooks';
import {
  useRunDocument,
  useSetDocumentParser,
  useSetDocumentPipelineParser,
} from '@/hooks/use-document-request';
import { IDocumentInfo } from '@/interfaces/database/document';
import { IChangeParserRequestBody } from '@/interfaces/request/document';
import { pickByBackend } from '@/utils/backend-variant';
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';

export const useChangeDocumentParser = () => {
  const { t } = useTranslation();
  const { setDocumentParser, loading } = useSetDocumentParser();
  const { setDocumentPipelineParser, loading: pipelineParserLoading } =
    useSetDocumentPipelineParser();
  const { runDocumentByIds } = useRunDocument();
  const [record, setRecord] = useState<IDocumentInfo>({} as IDocumentInfo);

  const {
    visible: changeParserVisible,
    hideModal: hideChangeParserModal,
    showModal: showChangeParserModal,
  } = useSetModalState();

  const onChangeParserOk = useCallback(
    async (parserConfigInfo: IChangeParserRequestBody) => {
      if (record?.id && record?.dataset_id) {
        // The Go document endpoint takes `parser_id` and a pipeline-shaped
        // parser_config; the Python one keeps the legacy payload shape.
        const common = {
          parserId: parserConfigInfo.parser_id,
          pipelineId: parserConfigInfo.pipeline_id || '',
          documentId: record?.id,
          datasetId: record?.dataset_id,
          parserConfig: parserConfigInfo.parser_config,
        };
        const ret = await pickByBackend({
          go: () =>
            setDocumentPipelineParser({
              ...common,
              parseType: parserConfigInfo.parseType,
            }),
          python: () => setDocumentParser(common),
        })();
        if (ret === 0) {
          hideChangeParserModal();
          // Changing the parser only changes how the *next* parse reads the file:
          // the chunks already indexed were produced by the old one and keep being
          // retrieved until the document is parsed again. Offer the rebuild here,
          // because "switched to Plain Text but the answers still show the old
          // garbled text" is otherwise the next bug report.
          if ((record?.chunk_count ?? 0) > 0) {
            Modal.confirm({
              title: t('knowledgeDetails.reparseAfterParserChangeTitle'),
              content: t('knowledgeDetails.reparseAfterParserChangeTip'),
              okText: t('knowledgeDetails.reparseNow'),
              cancelText: t('common.cancel'),
              onOk: () =>
                runDocumentByIds({
                  documentIds: [record.id],
                  run: 1,
                  // Drop the old chunks before rebuilding, and keep the
                  // document-level parser config instead of re-applying the KB's.
                  option: { delete: true, apply_kb: false },
                }),
            });
          }
        }
      }
    },
    [
      record?.id,
      record?.dataset_id,
      record?.chunk_count,
      setDocumentParser,
      setDocumentPipelineParser,
      hideChangeParserModal,
      runDocumentByIds,
      t,
    ],
  );

  const handleShowChangeParserModal = useCallback(
    (row: IDocumentInfo) => {
      setRecord(row);
      showChangeParserModal();
    },
    [showChangeParserModal],
  );

  return {
    changeParserLoading: loading || pipelineParserLoading,
    onChangeParserOk,
    changeParserVisible,
    hideChangeParserModal,
    showChangeParserModal: handleShowChangeParserModal,
    changeParserRecord: record,
  };
};

export type UseChangeDocumentParserShowType = Pick<
  ReturnType<typeof useChangeDocumentParser>,
  'showChangeParserModal'
>;

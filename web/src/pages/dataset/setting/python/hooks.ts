import { useSetModalState } from '@/hooks/common-hooks';

import { PermissionRole } from '@/constants/permission';
import {
  useFetchDatasetAuthorization,
  useFetchKnowledgeBaseConfiguration,
} from '@/hooks/use-knowledge-request';
import { useSelectParserList } from '@/hooks/use-user-setting-request';
import { checkEmbedding } from '@/services/knowledge-service';
import { useIsFetching } from '@tanstack/react-query';
import { pick } from 'lodash';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UseFormReturn } from 'react-hook-form';
import { useParams, useSearchParams } from 'react-router';
import { z } from 'zod';
import { formSchema } from './form-schema';

// Parser strategies outside the cable-document workflow stay supported by the
// backend but are hidden from the product's built-in parser picker.
const HiddenFields = [
  'email',
  'picture',
  'audio',
  'resume',
  'paper',
  'book',
  'laws',
  'presentation',
  'one',
  'tag',
  'knowledge_graph',
];

export function useSelectChunkMethodList(currentParserId?: string) {
  const parserList = useSelectParserList();
  const { t, i18n } = useTranslation();
  const hiddenCurrentParser = parserList.find(
    (x) => x.value === currentParserId && HiddenFields.includes(x.value),
  );
  const visibleParserList = parserList.filter(
    (x) => !HiddenFields.includes(x.value),
  );
  const translateParser = (parser: (typeof parserList)[number]) => {
    const key = `knowledgeConfiguration.parserLabel.${parser.value}`;
    return i18n.exists(key) ? { ...parser, label: t(key) } : parser;
  };

  return [
    ...visibleParserList.map(translateParser),
    ...(hiddenCurrentParser
      ? [{ ...translateParser(hiddenCurrentParser), disabled: true }]
      : []),
  ];
}

export function useHasParsedDocument(isEdit?: boolean) {
  const { data: knowledgeDetails } = useFetchKnowledgeBaseConfiguration({
    isEdit,
  });
  return knowledgeDetails.chunk_count > 0;
}

export const useFetchKnowledgeConfigurationOnMount = (
  form: UseFormReturn<z.infer<typeof formSchema>>,
) => {
  const { data: knowledgeDetails, loading } =
    useFetchKnowledgeBaseConfiguration();
  const isCustomPermission =
    knowledgeDetails.permission === PermissionRole.Custom;
  // Only asked for when the dataset is `custom`: the subject lists are a
  // manager's view, and the request would be refused for anyone else.
  const { data: authorization } = useFetchDatasetAuthorization({
    datasetId: knowledgeDetails.id,
    enabled: !!knowledgeDetails.id && isCustomPermission,
  });

  useEffect(() => {
    const parser_config = {
      ...form.formState?.defaultValues?.parser_config,
      ...knowledgeDetails.parser_config,
    };
    const formValues = {
      ...pick({ ...knowledgeDetails, parser_config: parser_config }, [
        'description',
        'name',
        'permission',
        'language',
        'parser_config',
        'connectors',
        'pagerank',
        'avatar',
      ]),
      embedding_model: knowledgeDetails.embedding_model,
      chunk_method: knowledgeDetails.chunk_method,
    } as z.infer<typeof formSchema>;
    form.reset(formValues);
  }, [form, knowledgeDetails]);

  // The granted subjects live in their own table, so they are echoed into the
  // picker once they arrive. Only these two fields are touched: resetting the
  // whole form here would discard edits made while the request was in flight.
  useEffect(() => {
    if (!isCustomPermission) {
      return;
    }
    form.setValue('department_ids', authorization.department_ids);
    form.setValue('user_ids', authorization.user_ids);
  }, [authorization, form, isCustomPermission]);

  return { knowledgeDetails, loading };
};

export const useSelectKnowledgeDetailsLoading = () =>
  useIsFetching({ queryKey: ['fetchKnowledgeDetail'] }) > 0;

export const useRenameKnowledgeTag = () => {
  const [tag, setTag] = useState<string>('');
  const {
    visible: tagRenameVisible,
    hideModal: hideTagRenameModal,
    showModal: showFileRenameModal,
  } = useSetModalState();

  const handleShowTagRenameModal = useCallback(
    (record: string) => {
      setTag(record);
      showFileRenameModal();
    },
    [showFileRenameModal],
  );

  return {
    initialName: tag,
    tagRenameVisible,
    hideTagRenameModal,
    showTagRenameModal: handleShowTagRenameModal,
  };
};

export const useHandleKbEmbedding = () => {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const knowledgeBaseId = searchParams.get('id') || id;
  const handleChange = useCallback(
    async ({ embed_id }: { embed_id: string }) => {
      const res = await checkEmbedding(knowledgeBaseId || '', {
        embd_id: embed_id,
      });
      return res.data;
    },
    [knowledgeBaseId],
  );
  return {
    handleChange,
  };
};

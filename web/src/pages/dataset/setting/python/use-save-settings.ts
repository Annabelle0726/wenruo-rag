import message from '@/components/ui/message';
import { ParseType } from '@/constants/knowledge';
import { PermissionRole } from '@/constants/permission';
import { normalizeParserConfig } from '@/hooks/parser-config-utils';
import {
  DatasetAuthorizationKeys,
  KnowledgeApiAction,
} from '@/hooks/use-knowledge-request';
import {
  updateDatasetAuthorization,
  updateKb,
} from '@/services/knowledge-service';
import { pick } from 'lodash';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { formSchema } from './form-schema';

const DatasetSettingsKeys = {
  save: () => ['saveDatasetSettings'] as const,
  details: () => [KnowledgeApiAction.FetchKnowledgeDetail] as const,
  lists: () => [KnowledgeApiAction.FetchKnowledgeListByPage] as const,
};

export function useSaveSettings() {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  return useMutation({
    mutationKey: DatasetSettingsKeys.save(),
    mutationFn: async ({
      datasetId,
      values,
    }: {
      datasetId: string;
      values: z.infer<typeof formSchema>;
    }) => {
      const {
        permission = PermissionRole.Me,
        department_ids = [],
        user_ids = [],
        parser_config: parserConfig,
      } = values;
      const { data: result } = await updateKb(datasetId, {
        ...pick(values, [
          'name',
          'description',
          'avatar',
          'embedding_model',
          'parse_type',
          'language',
          'pagerank',
          'connectors',
        ]),
        pipeline_id:
          values.parse_type === ParseType.BuiltIn ? null : values.pipeline_id,
        chunk_method:
          values.parse_type === ParseType.BuiltIn ? values.chunk_method : null,
        parser_config: parserConfig
          ? normalizeParserConfig({
              ...parserConfig,
              image_context_size: parserConfig.image_table_context_window,
              table_context_size: parserConfig.image_table_context_window,
              children_delimiter: parserConfig.enable_children
                ? parserConfig.children_delimiter
                : '',
            })
          : undefined,
      });
      // HTTP 200 can contain a business error. Do not continue that save.
      if (result.code !== 0) return result;
      const { data: authorization } = await updateDatasetAuthorization(
        datasetId,
        {
          permission,
          department_ids:
            permission === PermissionRole.Custom ? department_ids : [],
          user_ids: permission === PermissionRole.Custom ? user_ids : [],
        },
      );
      if (authorization.code === 0) {
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: DatasetSettingsKeys.details(),
          }),
          queryClient.invalidateQueries({
            queryKey: DatasetSettingsKeys.lists(),
          }),
          queryClient.invalidateQueries({
            queryKey: DatasetAuthorizationKeys.detail(datasetId),
          }),
        ]);
        message.success(t('message.updated'));
      }
      return authorization;
    },
  });
}

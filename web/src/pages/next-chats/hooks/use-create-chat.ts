import { useSetModalState } from '@/hooks/common-hooks';
import { useCreateChat } from '@/hooks/use-chat-request';
import { useFetchDefaultModelDictionary } from '@/hooks/use-llm-request';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { warnAboutEmptyModel } from '@/hooks/use-warn-empty-model';
import { isEmpty } from 'lodash';
import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';

export const useCreateChatDialog = () => {
  const { t } = useTranslation();
  const {
    visible: createChatVisible,
    hideModal: hideCreateChatModal,
    showModal: openCreateChatModal,
  } = useSetModalState();
  const { createChat, loading: createLoading } = useCreateChat();
  // Read without the warning: the dialog must not open with a warning modal on top
  // of it, because that modal's overlay swallows the Save click and the create then
  // looks frozen. The check happens on the click instead, below.
  const defaultModelDictionary = useFetchDefaultModelDictionary();
  const { navigateToModelSetting } = useNavigatePage();

  /**
   * Assumes a model is configured, or sends the operator to configure one.
   *
   * An assistant created without a default chat model cannot answer — the completion
   * path refuses — so the dialog is not opened at all in that case; the warning that
   * used to appear over it was the only thing saying why, and it arrived after the
   * operator had already started naming the assistant.
   */
  const showCreateChatModal = useCallback(() => {
    if (
      isEmpty(defaultModelDictionary.embd_id) ||
      isEmpty(defaultModelDictionary.llm_id)
    ) {
      warnAboutEmptyModel(t, navigateToModelSetting);
      return;
    }

    openCreateChatModal();
  }, [defaultModelDictionary, navigateToModelSetting, openCreateChatModal, t]);

  const InitialData = useMemo(
    () => ({
      name: '',
      icon: '',
      language: 'English',
      description: '',
      dataset_ids: [],
      // The prompt and retrieval defaults (system prompt, opener, no-result
      // answer, similarity threshold, vector weight, top N, rerank candidates)
      // belong to the backend, which applies the cable vertical values in
      // api/db/cable_defaults.py. Sending them from here would override those
      // defaults with a second copy that has to be kept in step.
      prompt_config: {
        quote: true,
        keyword: false,
        tts: false,
        refine_multiturn: false,
        use_kg: false,
        reasoning: false,
        parameters: [
          { key: 'knowledge', optional: false },
          { key: 'date', optional: true },
        ],
        toc_enhance: false,
      },
      llm_id: defaultModelDictionary?.llm_id,
      tenant_llm_id: defaultModelDictionary?.llm_id,
      llm_setting: {},
    }),
    [defaultModelDictionary?.llm_id],
  );

  const onCreateChatOk = useCallback(
    async (name: string) => {
      const ret = await createChat({ ...InitialData, name });
      if (ret === 0) {
        hideCreateChatModal();
      }
    },
    [InitialData, createChat, hideCreateChatModal],
  );

  return {
    createChatLoading: createLoading,
    onCreateChatOk,
    createChatVisible,
    hideCreateChatModal,
    showCreateChatModal,
  };
};

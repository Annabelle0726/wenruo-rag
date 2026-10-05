import { ButtonLoading } from '@/components/ui/button';
import { useCallback } from 'react';
import { useFormContext } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { z } from 'zod';
import { formSchema } from './form-schema';
import { useSaveSettings } from './use-save-settings';

export function SavingButton() {
  const { mutateAsync: saveSettings, isPending } = useSaveSettings();
  const form = useFormContext<z.infer<typeof formSchema>>();
  const { id: datasetId } = useParams();
  const { t } = useTranslation();
  const handleSave = useCallback(async () => {
    if (!datasetId) return;
    try {
      await form.handleSubmit(async (values) => {
        await saveSettings({ datasetId, values });
      })();
    } catch {
      // The request layer reports failures; preserve the draft for retry.
    }
  }, [datasetId, form, saveSettings]);
  return (
    <ButtonLoading
      type="button"
      loading={form.formState.isSubmitting || isPending}
      data-testid="ds-settings-page-save-btn"
      onClick={handleSave}
    >
      {t('knowledgeConfiguration.save')}
    </ButtonLoading>
  );
}

import {
  FormFieldConfig,
  FormFieldType,
  RenderField,
} from '@/components/dynamic-form';
import { ModelTreeSelect, ModelTypeMap } from '@/components/model-tree-select';
import { SelectWithSearch } from '@/components/originui/select-with-search';
import { SliderInputFormField } from '@/components/slider-input-form-field';
import { Button } from '@/components/ui/button';
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Spin } from '@/components/ui/spin';
import { Switch } from '@/components/ui/switch';
import { useTranslate } from '@/hooks/common-hooks';
import { cn } from '@/lib/utils';
import { history } from '@/utils/simple-history-util';
import { t } from 'i18next';
import { Settings } from 'lucide-react';
import { useCallback, useContext, useEffect, useMemo, useState } from 'react';
import {
  ControllerRenderProps,
  FieldValues,
  useFormContext,
} from 'react-hook-form';
import { useLocation } from 'react-router';
import { DataSetContext } from '..';
import { MetadataType } from '../../../components/metedata/constant';
import {
  useManageMetadata,
  util,
} from '../../../components/metedata/hooks/use-manage-modal';

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import {
  IBuiltInMetadataItem,
  IMetaDataReturnJSONSettings,
} from '../../../components/metedata/interface';
import { ManageMetadataModal } from '../../../components/metedata/manage-modal';
import {
  useOwnerTenantId,
  useKnowledgeBaseContext,
} from '../../../contexts/knowledge-base-context';
import {
  useHandleKbEmbedding,
  useHasParsedDocument,
  useSelectChunkMethodList,
} from '../hooks';
interface IProps {
  line?: 1 | 2;
  isEdit?: boolean;
  label?: string;
  name?: string;
}

/**
 * The width a slider-plus-value control is allowed to take.
 *
 * The slider row is 25% label / 75% control, and inside that control the slider
 * (`w-full`) and the number input are laid out with `justify-between` - so on a
 * 1100px form the number landed some 630px away from the thumb it belongs to: the
 * slider read as one control and the value as a stray field at the panel's edge.
 * Capping the control group makes the two one object again, while the value box
 * still sits at the end of the slider it edits. Passed to the shared slider field
 * through its own `className`/`controlClassName`, so no other page changes.
 */
export const SLIDER_CONTROL_CLASS = 'max-w-md';

export function ChunkMethodItem(props: IProps) {
  const { line, name = 'parser_id' } = props;
  const { t } = useTranslate('knowledgeConfiguration');
  const form = useFormContext();
  const currentParserId = form.watch(name);
  const parserList = useSelectChunkMethodList(currentParserId);

  return (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem className="items-center gap-1">
          <div
            className={
              line === 1 ? 'flex items-center gap-1' : 'flex flex-col gap-1'
            }
          >
            <FormLabel
              required
              tooltip={t('chunkMethodTip')}
              className={cn('text-sm', {
                'w-1/4 whitespace-pre-wrap': line === 1,
              })}
            >
              {t('builtIn')}
            </FormLabel>
            <div className={line === 1 ? 'w-3/4' : 'w-full'}>
              <FormControl>
                <SelectWithSearch
                  {...field}
                  options={parserList}
                  placeholder={t('chunkMethodPlaceholder')}
                />
              </FormControl>
            </div>
          </div>
          <div className="flex pt-1">
            <div className={line === 1 ? 'w-1/4' : ''}></div>
            <FormMessage />
          </div>
        </FormItem>
      )}
    />
  );
}

export const EmbeddingSelect = ({
  isEdit,
  field,
  name,
  disabled = false,
  testId,
  ownerTenantId,
}: {
  isEdit: boolean;
  field: FieldValues;
  name?: string;
  disabled?: boolean;
  testId?: string;
  ownerTenantId?: string;
}) => {
  const { t } = useTranslate('knowledgeConfiguration');
  const form = useFormContext();
  const { handleChange } = useHandleKbEmbedding();

  const oldValue = useMemo(() => {
    const embdStr = form.getValues(name || 'embedding_model');
    return embdStr || '';
  }, [form, name]);
  const [loading, setLoading] = useState(false);
  return (
    <Spin
      spinning={loading}
      className={cn('rounded-lg after:bg-bg-base', {
        'opacity-20': loading,
      })}
    >
      <ModelTreeSelect
        modelTypes={ModelTypeMap.embd_id}
        onChange={async (value) => {
          field.onChange(value);
          if (isEdit && disabled) {
            setLoading(true);
            const res = await handleChange({
              embed_id: value,
            });
            if (res.code !== 0) {
              field.onChange(oldValue);
            }
            setLoading(false);
          }
        }}
        ownerTenantId={ownerTenantId}
        disabled={disabled && !isEdit}
        value={field.value}
        placeholder={t('embeddingModelPlaceholder')}
        testId={testId}
      />
    </Spin>
  );
};

export function EmbeddingModelItem({
  line = 1,
  isEdit,
  ownerTenantId,
}: IProps & { ownerTenantId?: string }) {
  const { t } = useTranslate('knowledgeConfiguration');
  const form = useFormContext();
  const disabled = useHasParsedDocument(isEdit);
  return (
    <>
      <FormField
        control={form.control}
        name={'embedding_model'}
        render={({ field }) => (
          <FormItem className={cn('items-center space-y-0')}>
            <div
              className={cn('flex', {
                'items-center': line === 1,
                'flex-col gap-1': line === 2,
              })}
            >
              <FormLabel
                required
                tooltip={t('embeddingModelTip')}
                className={cn('text-sm whitespace-wrap', {
                  'w-1/4': line === 1,
                })}
              >
                {t('embeddingModel')}
              </FormLabel>
              <div className={cn('text-text-primary', { 'w-3/4': line === 1 })}>
                <FormControl>
                  <EmbeddingSelect
                    isEdit={!!isEdit}
                    field={field}
                    disabled={disabled}
                    testId="ds-settings-basic-embedding-model-select"
                    ownerTenantId={ownerTenantId}
                  ></EmbeddingSelect>
                </FormControl>
              </div>
            </div>
            <div className="flex pt-1">
              <div className={line === 1 ? 'w-1/4' : ''}></div>
              <FormMessage />
            </div>
          </FormItem>
        )}
      />
    </>
  );
}

export function EnableAutoGenerateItem() {
  const { t } = useTranslate('knowledgeConfiguration');
  const form = useFormContext();

  return (
    <FormField
      control={form.control}
      name={'enableAutoGenerate'}
      render={({ field }) => (
        <FormItem className="items-center space-y-0">
          <div className="flex items-center">
            <FormLabel
              tooltip={t('enableAutoGenerateTip')}
              className="text-sm  whitespace-wrap w-1/4"
            >
              {t('enableAutoGenerate')}
            </FormLabel>
            <div className="text-muted-foreground w-3/4">
              <FormControl>
                <Switch
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              </FormControl>
            </div>
          </div>
          <div className="flex pt-1">
            <div className="w-1/4"></div>
            <FormMessage />
          </div>
        </FormItem>
      )}
    />
  );
}

export function ImageContextWindow({
  controlClassName,
}: {
  controlClassName?: string;
} = {}) {
  const { t } = useTranslate('knowledgeConfiguration');
  const form = useFormContext();

  return (
    <FormField
      control={form.control}
      name="parser_config.image_table_context_window"
      render={({ field }) => (
        <FormItem>
          <FormControl>
            <SliderInputFormField
              {...field}
              className={controlClassName}
              label={t('imageTableContextWindow')}
              tooltip={t('imageTableContextWindowTip')}
              defaultValue={0}
              min={0}
              max={256}
              sliderTestId="ds-settings-parser-image-table-context-window-slider"
              numberInputTestId="ds-settings-parser-image-table-context-window-input"
            />
          </FormControl>
          <div className="flex pt-1">
            <div className="w-1/4"></div>
            <FormMessage />
          </div>
        </FormItem>
      )}
    />
  );
}

export function OverlappedPercent() {
  return (
    <SliderInputFormField
      percentage={true}
      name="parser_config.overlapped_percent"
      label={t('knowledgeConfiguration.overlappedPercent')}
      tooltip={t('knowledgeConfiguration.overlappedPercentTip')}
      className={SLIDER_CONTROL_CLASS}
      max={0.3}
      step={0.01}
      sliderTestId="ds-settings-parser-overlapped-percent-slider"
      numberInputTestId="ds-settings-parser-overlapped-percent-input"
    ></SliderInputFormField>
  );
}

export function AutoMetadata({
  type = MetadataType.Setting,
  otherData,
  switchPlacement = 'end',
}: {
  type?: MetadataType;
  otherData?: Record<string, any>;
  /**
   * Where this field's on/off switch sits. The default is the long-standing row -
   * the 设置 button at the control column's start and the switch at its far end -
   * and it is what the parsing dialogs keep. `'control'` groups the switch with the
   * button instead, so both belong visibly to the label beside them and the switch
   * no longer lands past the panel's right edge, hundreds of pixels from its own
   * field. Only the parser page asks for it.
   */
  switchPlacement?: 'end' | 'control';
}) {
  // get metadata field
  const location = useLocation();
  const form = useFormContext();
  const datasetContext = useContext(DataSetContext);
  const { knowledgeBase } = useKnowledgeBaseContext();
  const {
    manageMetadataVisible,
    showManageMetadataModal,
    hideManageMetadataModal,
    tableData,
    config: metadataConfig,
  } = useManageMetadata();

  const handleClickOpenMetadata = useCallback(() => {
    const metadata = form.getValues('parser_config.metadata');
    const builtInMetadata = form.getValues('parser_config.built_in_metadata');
    const tableMetaData = util.metaDataSettingJSONToMetaDataTableData(metadata);
    showManageMetadataModal({
      metadata: tableMetaData,
      isCanAdd: true,
      type: type,
      record: otherData,
      builtInMetadata,
      secondTitle: knowledgeBase ? (
        <div className="w-full flex items-center gap-1 text-sm text-text-secondary">
          <RAGFlowAvatar
            avatar={knowledgeBase.avatar}
            name={knowledgeBase.name}
            className="size-8"
          />
          <div className="text-text-primary text-base space-y-1 truncate overflow-hidden">
            {knowledgeBase.name}
          </div>
        </div>
      ) : (
        <></>
      ),
    });
  }, [form, otherData, showManageMetadataModal, knowledgeBase, type]);

  useEffect(() => {
    const locationState = location.state as
      | { openMetadata?: boolean }
      | undefined;
    if (locationState?.openMetadata && !datasetContext?.loading) {
      const timer = setTimeout(() => {
        handleClickOpenMetadata();
        clearTimeout(timer);
      }, 0);
      locationState.openMetadata = false;
      history.replace({ ...location }, locationState);
    }
  }, [location, handleClickOpenMetadata, datasetContext]);

  const autoMetadataField: FormFieldConfig = {
    name: 'parser_config.enable_metadata',
    label: t('knowledgeConfiguration.autoMetadata'),
    type: FormFieldType.Custom,
    horizontal: true,
    defaultValue: true,
    tooltip: t('knowledgeConfiguration.autoMetadataTip'),
    render: (fieldProps: ControllerRenderProps) => (
      <div
        className={cn(
          'flex items-center',
          switchPlacement === 'control' ? 'gap-3' : 'justify-between',
        )}
      >
        <Button
          type="button"
          variant="ghost"
          onClick={handleClickOpenMetadata}
          data-testid="ds-settings-metadata-open-modal-btn"
        >
          <div className="flex items-center gap-2">
            <Settings />
            {t('knowledgeConfiguration.settings')}
          </div>
        </Button>
        <Switch
          checked={fieldProps.value}
          onCheckedChange={fieldProps.onChange}
          data-testid="ds-settings-metadata-switch"
        />
      </div>
    ),
  };

  const handleSaveMetadata = (data?: {
    metadata?: IMetaDataReturnJSONSettings;
    builtInMetadata?: IBuiltInMetadataItem[];
  }) => {
    form.setValue('parser_config.metadata', data?.metadata || []);
    form.setValue(
      'parser_config.built_in_metadata',
      data?.builtInMetadata || [],
    );
    form.setValue('parser_config.enable_metadata', true);
  };
  return (
    <>
      <RenderField field={autoMetadataField} />
      {manageMetadataVisible && (
        <ManageMetadataModal
          title={
            metadataConfig.title || (
              <div className="flex flex-col gap-2">
                <div className="text-base font-normal">
                  {t('knowledgeDetails.metadata.metadataGenerationSettings')}
                </div>
                <div className="text-sm text-text-secondary">
                  {t('knowledgeDetails.metadata.changesAffectNewParses')}
                </div>
              </div>
            )
          }
          visible={manageMetadataVisible}
          hideModal={hideManageMetadataModal}
          // selectedRowKeys={selectedRowKeys}
          tableData={tableData}
          isCanAdd={metadataConfig.isCanAdd}
          isDeleteSingleValue={metadataConfig.isDeleteSingleValue}
          type={metadataConfig.type}
          otherData={metadataConfig.record}
          isShowDescription={true}
          isShowValueSwitch={true}
          isVerticalShowValue={false}
          builtInMetadata={metadataConfig.builtInMetadata}
          secondTitle={metadataConfig.secondTitle}
          success={(data?: {
            metadata?: IMetaDataReturnJSONSettings;
            builtInMetadata?: IBuiltInMetadataItem[];
          }) => {
            handleSaveMetadata(data);
          }}
          testId="ds-settings-metadata-modal"
          okButtonTestId="ds-settings-metadata-modal-save-btn"
          addButtonTestId="ds-settings-metadata-add-btn"
          nestedModalTestId="ds-settings-metadata-add-modal"
          nestedModalOkButtonTestId="ds-settings-metadata-add-modal-confirm-btn"
        />
      )}
    </>
  );
}

export const LLMSelect = ({
  isEdit,
  field,
  disabled = false,
  ownerTenantId,
}: {
  isEdit: boolean;
  field: FieldValues;
  name?: string;
  disabled?: boolean;
  ownerTenantId?: string;
}) => {
  const { t } = useTranslate('knowledgeConfiguration');
  return (
    <ModelTreeSelect
      modelTypes={ModelTypeMap.llm_id}
      onChange={(value) => {
        field.onChange(value);
      }}
      disabled={disabled && !isEdit}
      value={field.value}
      placeholder={t('embeddingModelPlaceholder')}
      ownerTenantId={ownerTenantId}
    />
  );
};

export function LLMModelItem({
  line = 1,
  isEdit,
  label,
  name,
  ownerTenantId,
}: IProps & { ownerTenantId?: string }) {
  const { t } = useTranslate('knowledgeConfiguration');
  const form = useFormContext();
  // const disabled = useHasParsedDocument(isEdit);
  return (
    <>
      <FormField
        control={form.control}
        name={name ?? 'llm_id'}
        render={({ field }) => (
          <FormItem className={cn('items-center space-y-0')}>
            <div
              className={cn('flex', {
                'items-center gap-1': line === 1,
                'flex-col gap-1': line === 2,
              })}
            >
              <FormLabel
                tooltip={t('globalIndexModelTip')}
                className={cn('text-sm  whitespace-wrap ', {
                  'w-1/4': line === 1,
                })}
              >
                {label ?? t('llmModel')}
              </FormLabel>
              <div className={cn('text-text-primary', { 'w-3/4': line === 1 })}>
                <FormControl>
                  <LLMSelect
                    isEdit={!!isEdit}
                    field={field}
                    disabled={false}
                    ownerTenantId={ownerTenantId}
                  ></LLMSelect>
                </FormControl>
              </div>
            </div>
            <div className="flex pt-1">
              <div className={line === 1 ? 'w-1/4' : ''}></div>
              <FormMessage />
            </div>
          </FormItem>
        )}
      />
    </>
  );
}

export function GlobalIndexModelItem() {
  const { t } = useTranslate('knowledgeConfiguration');
  const ownerTenantId = useOwnerTenantId();
  return (
    <LLMModelItem
      isEdit={true}
      name="parser_config.llm_id"
      label={t('globalIndexModel')}
      ownerTenantId={ownerTenantId}
    />
  );
}

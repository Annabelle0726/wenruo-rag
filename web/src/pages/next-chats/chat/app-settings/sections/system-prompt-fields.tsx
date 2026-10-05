'use client';

import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Textarea } from '@/components/ui/textarea';
import { prefixName } from '@/utils/form';
import { getDirAttribute } from '@/utils/text-direction';
import { useCallback, useEffect, useRef } from 'react';
import { useFormContext } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { DynamicVariableForm } from '../dynamic-variable';

type SystemPromptFieldsProps = { prefix?: string };

/** Minimum height of the prompt box: roughly the cable prompt's first screen. */
const SystemPromptMinHeight = 'min-h-[10rem]';

// 默认线缆系统提示词
const CABLE_DEFAULT_SYSTEM_PROMPT = `你是一位经验丰富且亲切的线缆技术专家顾问。

【沟通风格】
- 请使用自然、流畅、口语化的语言回答问题，语气生动亲切。
- 避免像机器一样机械地罗列硬邦邦的规范条款，把复杂的工程标准用通俗易懂的专业语言表达出来。

【回答与推理原则】
1. 自然表达与拒答：如果知识库中完全没有包含回答问题所需的信息，请用自然的口吻告知用户暂未查到相关资料即可，无需使用僵硬固定的模板（如“未找到您想要的答案”）。
2. 弹性与例外条款优先：在回答基于标准规范的逻辑判定或选型问题时，必须优先检查标准文本中是否存在“例外条款”、“供需双方协商确定”、“补充协议规定”或“特殊工况说明”等弹性规定。只要标准允许协商或存在例外，不得仅凭通用常识直接否定。
3. 合理工程推理：允许基于知识库提取出的物理结构特征（如铠装类型、材质、截面等），结合线缆工程常识进行合理的适用性分析。

以下是知识库：
{knowledge}
以上是知识库。`;

export function SystemPromptFields({ prefix = '' }: SystemPromptFieldsProps) {
  const { t } = useTranslation();
  const form = useFormContext();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const fieldName = prefixName(prefix, 'prompt_config.system');
  const systemPromptValue = form.watch(fieldName);

  // 💡 如果系统提示词为空，自动填充线缆默认 Prompt 并清除报错
  useEffect(() => {
    if (!systemPromptValue) {
      form.setValue(fieldName, CABLE_DEFAULT_SYSTEM_PROMPT, {
        shouldValidate: true,
        shouldDirty: false,
      });
    }
  }, [form, fieldName, systemPromptValue]);

  const resizeToContent = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, []);

  useEffect(() => {
    resizeToContent();
  }, [resizeToContent, systemPromptValue]);

  return (
    <div className="space-y-6">
      <FormField
        control={form.control}
        name={fieldName}
        render={({ field }) => (
          <FormItem>
            <FormLabel>{t('chat.system')}</FormLabel>
            <FormControl>
              <Textarea
                {...field}
                ref={(element: HTMLTextAreaElement | null) => {
                  textareaRef.current = element;
                  field.ref(element);
                }}
                rows={8}
                className={`${SystemPromptMinHeight} max-h-[45vh] resize-y overflow-y-auto`}
                placeholder={t('chat.systemPlaceholder')}
                dir={getDirAttribute(systemPromptValue || '')}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <DynamicVariableForm
        name={prefixName(prefix, 'prompt_config.parameters')}
      ></DynamicVariableForm>
    </div>
  );
}
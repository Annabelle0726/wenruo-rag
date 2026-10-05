'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';
import { Eye, EyeOff, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'prefix'> {
  value?: string | number | readonly string[] | undefined;
  prefix?: React.ReactNode;
  suffix?: React.ReactNode;
  rootClassName?: string;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className,
      rootClassName,
      type,
      value,
      onChange,
      prefix,
      suffix,
      ...props
    },
    ref,
  ) => {
    const isControlled = value !== undefined;
    const { defaultValue, ...restProps } = props;
    const inputValue = isControlled ? value : defaultValue;
    const [showPassword, setShowPassword] = useState(false);
    const [prefixWidth, setPrefixWidth] = useState(0);
    const [suffixWidth, setSuffixWidth] = useState(0);

    const prefixRef = useRef<HTMLSpanElement>(null);
    const suffixRef = useRef<HTMLSpanElement>(null);

    useEffect(() => {
      if (prefixRef.current) {
        setPrefixWidth(prefixRef.current.offsetWidth);
      }
      if (suffixRef.current) {
        setSuffixWidth(suffixRef.current.offsetWidth);
      }
    }, [prefix, suffix, prefixRef, suffixRef]);

    const handleChange: React.ChangeEventHandler<HTMLInputElement> = (e) => {
      if (type === 'number') {
        const numValue = e.target.value === '' ? '' : Number(e.target.value);
        onChange?.({
          ...e,
          target: {
            ...e.target,
            value: numValue,
          },
        } as React.ChangeEvent<HTMLInputElement>);
      } else {
        onChange?.(e);
      }
    };

    const isPasswordInput = type === 'password';

    const inputEl = useMemo(
      () => (
        <input
          ref={ref}
          type={isPasswordInput && showPassword ? 'text' : type}
          className={cn(
            'peer/input',
            /* 基础高度与边框：剔除灰暗的 border-0.5，引入清晰的细边框与精致圆角 */
            'flex h-10 w-full rounded-xl border border-cable-hairline bg-bg-input px-3.5 py-2 text-sm text-text-primary outline-none transition-all duration-200',
            /* 文件与占位符样式：提亮 Placeholder 对比度 */
            'file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-text-secondary/70',
            /* Hover & Focus 状态：增加明显的高亮边框反馈 */
            'hover:border-cable-border-hover',
            'focus-visible:border-cable-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cable-accent/20',
            'disabled:cursor-not-allowed disabled:opacity-50',
            type === 'number' &&
              '[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none',
            className,
          )}
          style={{
            paddingInlineStart:
              !!prefix && prefixWidth ? `${prefixWidth}px` : '',
            paddingInlineEnd: isPasswordInput
              ? '40px'
              : suffix
                ? `${suffixWidth}px`
                : '',
          }}
          value={inputValue ?? ''}
          onChange={handleChange}
          {...restProps}
        />
      ),
      [
        prefixWidth,
        suffixWidth,
        isPasswordInput,
        showPassword,
        inputValue,
        className,
        type,
        handleChange,
        restProps,
        ref,
        prefix,
        suffix,
      ],
    );

    if (prefix || suffix || isPasswordInput) {
      return (
        <div className={cn('relative', rootClassName)}>
          {prefix && (
            <span
              ref={prefixRef}
              className="absolute start-0 top-[50%] translate-y-[-50%] text-text-secondary"
            >
              {prefix}
            </span>
          )}
          {inputEl}
          {suffix && (
            <span
              ref={suffixRef}
              className={cn('absolute end-0 top-[50%] translate-y-[-50%] text-text-secondary', {
                'end-14': isPasswordInput,
              })}
            >
              {suffix}
            </span>
          )}
          {isPasswordInput && (
            <button
              type="button"
              className="
                p-2 text-text-secondary hover:text-text-primary transition-colors
                absolute border-0 end-1 top-[50%] translate-y-[-50%]
                dark:peer-autofill/input:text-text-secondary-inverse
                dark:peer-autofill/input:hover:text-text-primary-inverse
                dark:peer-autofill/input:focus-visible:text-text-primary-inverse
              "
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? (
                <EyeOff className="size-[1.1em]" />
              ) : (
                <Eye className="size-[1.1em]" />
              )}
            </button>
          )}
        </div>
      );
    }

    return inputEl;
  },
);

Input.displayName = 'Input';

const ExpandedInput = Input;

const SearchInput = (props: InputProps) => {
  const { t } = useTranslation();
  return (
    <Input
      placeholder={t('common.search')}
      {...props}
      prefix={<Search className="ms-3 me-1 size-[1em]" />}
    />
  );
};

type Value = string | readonly string[] | number | undefined;

export const InnerBlurInput = React.forwardRef<
  HTMLInputElement,
  InputProps & { value: Value; onChange(value: Value): void }
>(({ value, onChange, ...props }, ref) => {
  const [val, setVal] = React.useState<Value>();

  const handleChange: React.ChangeEventHandler<HTMLInputElement> =
    React.useCallback((e) => {
      setVal(e.target.value);
    }, []);

  const handleBlur: React.FocusEventHandler<HTMLInputElement> =
    React.useCallback(
      (e) => {
        onChange?.(e.target.value);
      },
      [onChange],
    );

  React.useEffect(() => {
    setVal(value);
  }, [value]);

  return (
    <Input
      {...props}
      value={val}
      onBlur={handleBlur}
      onChange={handleChange}
      ref={ref}
    ></Input>
  );
});

InnerBlurInput.displayName = 'BlurInput';

if (process.env.NODE_ENV !== 'production') {
  InnerBlurInput.whyDidYouRender = true;
}

export const BlurInput = React.memo(InnerBlurInput);

export { ExpandedInput, Input, SearchInput };

type NumberInputProps = { onChange?(value: number): void } & InputProps;

export const NumberInput = React.forwardRef<
  HTMLInputElement,
  NumberInputProps & { value: Value; onChange(value: Value): void }
>(function NumberInput({ onChange, ...props }, ref) {
  return (
    <Input
      type="number"
      onChange={(ev) => {
        const value = ev.target.value;
        onChange?.(value === '' ? 0 : Number(value));
      }}
      {...props}
      ref={ref}
    ></Input>
  );
});
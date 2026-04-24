import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { IngredientList } from './IngredientList';

afterEach(() => {
  cleanup();
});

describe('IngredientList', () => {
  it('keeps the raw OCR text visible and only shows ingredient-matched detail cards', () => {
    render(
      <IngredientList
        ingredientsText={[
          '配料表：圆苞车前子壳粉、蛋白核小球藻粉、食用香精（含藏红花提取物）。产品类别：复合果蔬汁饮料',
          '温馨提示：开袋后及时饮用。食用限量：菊粉 ≤15克/天',
        ].join('\n')}
        ingredients={[
          {
            name: '圆苞车前子壳粉',
            risk: 'safe',
            description: '富含膳食纤维。',
          },
          {
            name: '蛋白核小球藻粉 ≤20克/天',
            risk: 'warning',
            description: '建议遵循每日食用上限。',
          },
          {
            name: '食用香精（含藏红花提取物）。产品类别：复合果蔬汁饮料',
            risk: 'safe',
            description: '用于增强整体风味。',
          },
          {
            name: '开袋后及时饮用。食用限量：菊粉 ≤15克/天',
            risk: 'warning',
            description: '这是提示语，不应该进入详情卡片。',
          },
        ]}
      />,
    );

    const rawSection = screen.getByText('识别到的原始配料信息').parentElement;
    const detailSection = screen.getByText('配料说明').parentElement;

    expect(rawSection).toBeTruthy();
    expect(detailSection).toBeTruthy();

    expect(within(rawSection as HTMLElement).getByText(/温馨提示：开袋后及时饮用/)).toBeTruthy();

    expect(within(detailSection as HTMLElement).getByText('圆苞车前子壳粉')).toBeTruthy();
    expect(within(detailSection as HTMLElement).getByText('蛋白核小球藻粉')).toBeTruthy();
    expect(within(detailSection as HTMLElement).getByText('食用香精（含藏红花提取物）')).toBeTruthy();
    expect(within(detailSection as HTMLElement).queryByText(/开袋后及时饮用/)).toBeNull();
    expect(within(detailSection as HTMLElement).queryByText(/产品类别：复合果蔬汁饮料/)).toBeNull();
  });

  it('only renders keywords from the ingredient label section', () => {
    render(
      <IngredientList
        ingredientsText={[
          '配料表：植物蛋白液（水）、食用葡萄糖',
          '致敏源信息：乳、花生、坚果及其果仁类、芝麻成分的食品',
          '制粒员：张三',
        ].join('\n')}
        ingredients={[
          {
            name: '植物蛋白液（水）',
            risk: 'warning',
            description: '用于提供植物蛋白来源。',
          },
          {
            name: '食用葡萄糖',
            risk: 'safe',
            description: '常见甜味配料。',
          },
          {
            name: '乳',
            risk: 'danger',
            description: '交叉污染风险声明，不是配料表关键词。',
          },
          {
            name: '花生',
            risk: 'danger',
            description: '交叉污染风险声明，不是配料表关键词。',
          },
          {
            name: '坚果及其果仁类',
            risk: 'danger',
            description: '交叉污染风险声明，不是配料表关键词。',
          },
          {
            name: '芝麻成分的食品',
            risk: 'danger',
            description: '交叉污染风险声明，不是配料表关键词。',
          },
          {
            name: '制粒员',
            risk: 'warning',
            description: 'OCR 误识别内容，不是配料表关键词。',
          },
        ]}
      />,
    );

    const detailSection = screen.getByText('配料说明').parentElement;
    expect(detailSection).toBeTruthy();

    expect(within(detailSection as HTMLElement).getByText('植物蛋白液（水）')).toBeTruthy();
    expect(within(detailSection as HTMLElement).getByText('食用葡萄糖')).toBeTruthy();
    expect(within(detailSection as HTMLElement).queryByText('乳')).toBeNull();
    expect(within(detailSection as HTMLElement).queryByText('花生')).toBeNull();
    expect(within(detailSection as HTMLElement).queryByText('坚果及其果仁类')).toBeNull();
    expect(within(detailSection as HTMLElement).queryByText('芝麻成分的食品')).toBeNull();
    expect(within(detailSection as HTMLElement).queryByText('制粒员')).toBeNull();
  });

  it('keeps additive amount qualifiers and normalizes comparison symbols', () => {
    render(
      <IngredientList
        ingredientsText={'配料表：黄油（添加量\\geqslant4%）、水'}
        ingredients={[
          {
            name: '黄油（添加量\\geqslant4%）',
            risk: 'warning',
            description: '动物性脂肪，饱和脂肪含量较高。',
          },
          {
            name: '水',
            risk: 'safe',
            description: '常见食品配料。',
          },
        ]}
      />,
    );

    const detailSection = screen.getByText('配料说明').parentElement;
    expect(detailSection).toBeTruthy();

    expect(within(detailSection as HTMLElement).getByText('黄油（添加量≥4%）')).toBeTruthy();
    expect(within(detailSection as HTMLElement).getByText('水')).toBeTruthy();
  });

  it('keeps mono and diglycerides as one ingredient keyword', () => {
    render(
      <IngredientList
        ingredientsText={'配料表：单、双甘油脂肪酸酯（添加量\\geqslant2.5%）、水'}
        ingredients={[
          {
            name: '单',
            risk: 'safe',
            description: '此处应与后一项合并展示。',
          },
          {
            name: '双甘油脂肪酸酯）（添加量\\geqslant2.5%）',
            risk: 'safe',
            description: '常见乳化剂，用于改善面团质地和稳定性。',
            function_category: '乳化剂',
          },
          {
            name: '水',
            risk: 'safe',
            description: '常见食品配料。',
          },
        ]}
      />,
    );

    const detailSection = screen.getByText('配料说明').parentElement;
    expect(detailSection).toBeTruthy();

    expect(
      within(detailSection as HTMLElement).getByText('单、双甘油脂肪酸酯（添加量≥2.5%）'),
    ).toBeTruthy();
    expect(within(detailSection as HTMLElement).getByText('水')).toBeTruthy();
    expect(within(detailSection as HTMLElement).queryByText('单')).toBeNull();
    expect(within(detailSection as HTMLElement).queryByText(/^双甘油脂肪酸酯/)).toBeNull();
  });
});

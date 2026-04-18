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
    const detailSection = screen.getByText('详细配料列表').parentElement;

    expect(rawSection).toBeTruthy();
    expect(detailSection).toBeTruthy();

    expect(within(rawSection as HTMLElement).getByText(/温馨提示：开袋后及时饮用/)).toBeTruthy();

    expect(within(detailSection as HTMLElement).getByText('圆苞车前子壳粉')).toBeTruthy();
    expect(within(detailSection as HTMLElement).getByText('蛋白核小球藻粉')).toBeTruthy();
    expect(within(detailSection as HTMLElement).getByText('食用香精（含藏红花提取物）')).toBeTruthy();
    expect(within(detailSection as HTMLElement).queryByText(/开袋后及时饮用/)).toBeNull();
    expect(within(detailSection as HTMLElement).queryByText(/产品类别：复合果蔬汁饮料/)).toBeNull();
  });
});

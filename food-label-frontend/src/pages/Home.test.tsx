import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiPost } from '@/api/client';
import Home from './Home';

vi.mock('@/api/client', () => ({
  apiPost: vi.fn(),
}));

const navigateMock = vi.fn();

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
}));

const apiPostMock = vi.mocked(apiPost);
const createObjectURLMock = vi.fn();
const revokeObjectURLMock = vi.fn();

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  localStorage.clear();
  vi.clearAllMocks();
});

describe('Home', () => {
  it('cleans stored analyzing preview when upload response fails', async () => {
    createObjectURLMock
      .mockReturnValueOnce('blob:preview')
      .mockReturnValueOnce('blob:analyzing-preview');
    URL.createObjectURL = createObjectURLMock;
    URL.revokeObjectURL = revokeObjectURLMock;
    apiPostMock.mockResolvedValue({
      code: 5000,
      message: '上传失败',
      data: null as unknown as { task_id: string },
    });

    const { container } = render(<Home />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(input).toBeTruthy();

    fireEvent.change(input!, {
      target: {
        files: [new File(['image'], 'label.png', { type: 'image/png' })],
      },
    });

    fireEvent.click(screen.getByText('开始智能分析'));

    await waitFor(() => {
      expect(screen.getByText('上传失败')).toBeTruthy();
    });

    expect(sessionStorage.getItem('latest_upload_preview')).toBeNull();
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:analyzing-preview');
    expect(navigateMock).not.toHaveBeenCalled();
  });
});

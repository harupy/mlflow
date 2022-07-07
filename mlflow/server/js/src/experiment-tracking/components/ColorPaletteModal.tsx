import { useState } from 'react';
import { Modal } from 'antd';

const COLORS = {
  // https://github.com/plotly/plotly.js/blob/fefa11cbd533d11dea7db55d5dbed76c6359cf89/src/components/color/attributes.js
  1: [
    '#1f77b4', // muted blue
    '#ff7f0e', // safety orange
    '#2ca02c', // cooked asparagus green
    '#d62728', // brick red
    '#9467bd', // muted purple
    '#8c564b', // chestnut brown
    '#e377c2', // raspberry yogurt pink
    '#7f7f7f', // middle gray
    '#bcbd22', // curry yellow-green
    '#17becf', // blue-teal
  ],
  2: ['#e69f00', '#56b4e9', '#009e73', '#f0e442', '#0072b2', '#d55e00', '#cc79a7', '#000000'],
  3: ['#ee6677', '#228833', '#4477aa', '#ccbb44', '#66ccee', '#aa3377', '#bbbbbb'],
  4: [
    '#88ccee',
    '#44aa99',
    '#117733',
    '#332288',
    '#ddcc77',
    '#999933',
    '#cc6677',
    '#882255',
    '#aa4499',
    '#dddddd',
  ],
  5: [
    '#bbcc33',
    '#aaaa00',
    '#77aadd',
    '#ee8866',
    '#eedd88',
    '#ffaabb',
    '#99ddff',
    '#44bb99',
    '#dddddd',
  ],
};

type ColorPaletteProps = {
  onSelect: (colors: string[]) => void;
};

const ColorPalette = ({ onSelect }: ColorPaletteProps) => {
  const [selectedKey, setSelectedKey] = useState<string | undefined>(undefined);

  const renderColorMap = (key: string, colors: string[]) => {
    const borderColor = selectedKey === key ? '#696969' : 'transparent';
    return (
      <div key={key} css={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span css={{ width: 30 }}>{key}</span>
        <table
          css={{
            width: '100%',
            height: '200',
            tableLayout: 'fixed',
            marginBottom: '3px',
            border: `3px solid ${borderColor}`,
          }}
        >
          <tbody>
            <tr
              css={{
                '&:hover': {
                  cursor: 'pointer',
                },
              }}
              onClick={() => {
                setSelectedKey(key);
                onSelect(colors);
              }}
            >
              {colors.map((color, i) => (
                <td key={i} css={{ background: color, height: 50 }} />
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    );
  };
  return <>{Object.entries(COLORS).map(([key, colors]) => renderColorMap(key, colors))}</>;
};

type ColorPaletteModalProps = {
  visible: boolean;
  onSelect: (colors: string[]) => void;
  onCancel: () => void;
};

export const ColorPaletteModal = ({ visible, onSelect, onCancel }: ColorPaletteModalProps) => (
  <Modal title='Color Palette' visible={visible} onCancel={onCancel} mask={false} footer={null}>
    <ColorPalette onSelect={onSelect} />
  </Modal>
);

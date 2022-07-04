const COLORS = {
  0: ['#e69f00', '#56b4e9', '#009e73', '#f0e442', '#0072b2', '#d55e00', '#cc79a7', '#000000'],
  1: ['#ee6677', '#228833', '#4477aa', '#ccbb44', '#66ccee', '#aa3377', '#bbbbbb'],
  2: [
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
  3: [
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

type ColorPaletteSelectorProps = {
  onChange: (colors: string[]) => void;
};

export const ColorPaletteSelector = ({ onChange }: ColorPaletteSelectorProps) => {
  const renderColorMap = (name: string | number, colors: string[]) => {
    return (
      <table css={{ width: '100%', height: '200', marginBottom: 5 }}>
        <tbody>
          <tr
            css={{
              // Prevent the rows from shrinking on hover
              '&:hover': {
                cursor: 'pointer',
                boxShadow: '0 0 4px gray',
              },
            }}
            onClick={() => onChange(colors)}
          >
            <td css={{ width: 30, textAlign: 'center' }}>{name}</td>
            {colors.map((color, i) => (
              <td key={i} css={{ background: color, height: 50 }} />
            ))}
          </tr>
        </tbody>
      </table>
    );
  };

  return Object.entries(COLORS).map(([key, colors]) =>
    renderColorMap(parseInt(key, 10) + 1, colors),
  );
};

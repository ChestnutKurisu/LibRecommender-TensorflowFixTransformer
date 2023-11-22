use std::hash::Hash;

use fxhash::FxHashMap;
use pyo3::prelude::FromPyObject;
use serde::{Deserialize, Serialize};

/// Analogy of `scipy.sparse.csr_matrix`
/// https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csr_matrix.html
#[derive(FromPyObject, Serialize, Deserialize)]
pub struct CsrMatrix<T, U> {
    #[pyo3(attribute("sparse_indices"))]
    pub indices: Vec<T>,
    #[pyo3(attribute("sparse_indptr"))]
    pub indptr: Vec<usize>,
    #[pyo3(attribute("sparse_data"))]
    pub data: Vec<U>,
}

impl<T: Copy + Eq + Hash + Ord, U: Copy> CsrMatrix<T, U> {
    pub fn values(&self) -> (&[T], &[usize], &[U]) {
        (&self.indices, &self.indptr, &self.data)
    }

    #[inline]
    pub fn n_rows(&self) -> usize {
        self.indptr.len() - 1
    }

    fn to_dok(&self, n_rows: Option<usize>) -> DokMatrix<T, U> {
        let mut data = Vec::new();
        let n_rows = n_rows.unwrap_or_else(|| self.n_rows());
        for i in 0..n_rows {
            if let Some(row) = get_row(self, i) {
                data.push(FxHashMap::from_iter(row))
            } else {
                data.push(FxHashMap::default());
            }
        }
        DokMatrix { data }
    }

    pub fn add(
        this: &CsrMatrix<T, U>,
        other: &CsrMatrix<T, U>,
        n_rows: Option<usize>,
    ) -> CsrMatrix<T, U> {
        let mut dok_matrix = this.to_dok(n_rows);
        dok_matrix.add(other).to_csr()
    }

    fn iter(&self) -> CsrMatrixIterator<T, U> {
        CsrMatrixIterator {
            matrix: self,
            row_idx: 0,
        }
    }
}

struct CsrMatrixIterator<'a, T, U> {
    matrix: &'a CsrMatrix<T, U>,
    row_idx: usize,
}

impl<'a, T, U> Iterator for CsrMatrixIterator<'a, T, U>
where
    T: Copy + Eq + Hash + Ord,
    U: Copy,
{
    type Item = Vec<(T, U)>;

    fn next(&mut self) -> Option<Self::Item> {
        let sparse_row = get_row(self.matrix, self.row_idx);
        self.row_idx += 1;
        sparse_row.map(|row| row.collect())
    }
}

pub(crate) fn get_row<'a, T, U>(
    matrix: &'a CsrMatrix<T, U>,
    i: usize,
) -> Option<impl Iterator<Item = (T, U)> + 'a>
where
    T: Copy + Eq + Hash + Ord + 'a,
    U: Copy + 'a,
{
    if i >= matrix.n_rows() {
        return None;
    }
    let start = matrix.indptr[i];
    let end = matrix.indptr[i + 1];
    if start == end {
        None
    } else {
        Some(index_iter(start, end, &matrix.indices, &matrix.data))
    }
}

fn index_iter<'a, T, U>(
    start: usize,
    end: usize,
    indices: &'a [T],
    data: &'a [U],
) -> impl Iterator<Item = (T, U)> + 'a
where
    T: Copy + Eq + Hash + Ord + 'a,
    U: Copy + 'a,
{
    let mut i = start;
    std::iter::from_fn(move || {
        let item = if i < end {
            Some((indices[i], data[i]))
        } else {
            None
        };
        i += 1;
        item
    })
}

/// Analogy of `scipy.sparse.dok_matrix`
/// https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.dok_matrix.html
pub struct DokMatrix<T = i32, U = f32> {
    data: Vec<FxHashMap<T, U>>,
}

impl<T, U> DokMatrix<T, U>
where
    T: Copy + Eq + Hash + Ord,
    U: Copy,
{
    fn add(&mut self, other: &CsrMatrix<T, U>) -> &Self {
        for (i, row) in other.iter().enumerate() {
            for (idx, dat) in row {
                let mapping = &mut self.data[i];
                mapping.insert(idx, dat);
            }
        }
        self
    }

    fn to_csr(&self) -> CsrMatrix<T, U> {
        let mut indices: Vec<T> = Vec::new();
        let mut indptr: Vec<usize> = vec![0];
        let mut data: Vec<U> = Vec::new();
        for d in self.data.iter() {
            if d.is_empty() {
                continue;
            }
            let mut mapping: Vec<(&T, &U)> = d.iter().collect();
            mapping.sort_unstable_by_key(|(i, _)| *i);
            let (idx, dat): (Vec<T>, Vec<U>) = mapping.into_iter().unzip();
            indices.extend(idx);
            data.extend(dat);
            indptr.push(indices.len());
        }
        CsrMatrix {
            indices,
            indptr,
            data,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_add_sparse_matrix() {
        // [[1, 0, 0], [0, 0, 1]]
        let mut matrix = CsrMatrix {
            indices: vec![0, 2],
            indptr: vec![0, 1, 2],
            data: vec![1, 1],
        };
        // [[0, 0, 0], [1, 0, 2], [3, 3, 0]]
        let matrix_large = CsrMatrix {
            indices: vec![0, 2, 0, 1],
            indptr: vec![0, 0, 2, 4],
            data: vec![1, 2, 3, 3],
        };
        // [[2, 0, 4]]
        let matrix_small = CsrMatrix {
            indices: vec![0, 2],
            indptr: vec![0, 2],
            data: vec![2, 4],
        };

        // [[1, 0, 0], [1, 0, 2], [3, 3, 0]]
        matrix = CsrMatrix::add(&matrix, &matrix_large, Some(3));
        assert_eq!(matrix.indices, vec![0, 0, 2, 0, 1]);
        assert_eq!(matrix.indptr, vec![0, 1, 3, 5]);
        assert_eq!(matrix.data, vec![1, 1, 2, 3, 3]);

        // [[2, 0, 4], [1, 0, 2], [3, 3, 0]]
        matrix = CsrMatrix::add(&matrix, &matrix_small, Some(3));
        assert_eq!(matrix.indices, vec![0, 2, 0, 2, 0, 1]);
        assert_eq!(matrix.indptr, vec![0, 2, 4, 6]);
        assert_eq!(matrix.data, vec![2, 4, 1, 2, 3, 3]);
    }

    #[test]
    #[should_panic(expected = "index out of bounds: the len is 2 but the index is 2")]
    fn test_add_insufficient_size() {
        let new_size = 2;
        // [[1, 0, 0], [0, 0, 1]]
        let matrix = CsrMatrix {
            indices: vec![0, 2],
            indptr: vec![0, 1, 2],
            data: vec![1, 1],
        };
        // [[0, 0, 0], [1, 0, 2], [3, 3, 0]]
        let matrix_large = CsrMatrix {
            indices: vec![0, 2, 0, 1],
            indptr: vec![0, 0, 2, 4],
            data: vec![1, 2, 3, 3],
        };
        CsrMatrix::add(&matrix, &matrix_large, Some(new_size));
    }
}

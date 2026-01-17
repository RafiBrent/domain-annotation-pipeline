process chop_pdb_from_directory {
    label 'sge_low'
    container 'domain-annotation-pipeline-script'
    // NOTE: Publishing disabled for large-scale runs to avoid millions of files in single directory
    // Chopped PDBs are only intermediate files - downstream processes access via work directories
    publishDir "${params.results_dir}/chopped_pdbs", mode: 'copy', enabled: params.debug

    input:
    tuple val(id), path(consensus_chunk)
    val pdb_directory
    path id_file

    output:
    tuple val(id), path('chopped_pdbs/*.pdb')

    script:
    """
    mkdir -p chopped_pdbs
    ${params.chop_pdb_script} --consensus ${consensus_chunk} --pdb-dir ${pdb_directory} --id-file ${id_file} --output chopped_pdbs
    """
}

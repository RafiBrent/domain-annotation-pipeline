process extract_pdb_from_directory {
    label 'sge_low'
    container 'domain-annotation-pipeline-script'

    input:
    tuple( val(id), path(id_file) )
    val pdb_directory

    output:
    tuple( val(id), path('*.pdb') )

    script:
    """
    ${params.extract_pdb_script} ${id_file} ${pdb_directory}
    """
}

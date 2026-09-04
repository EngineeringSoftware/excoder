package org.throwgen.core;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

public class LocalVariableTypeCollector extends VoidVisitorAdapter<Void> {
    private List<String> localVariables = new ArrayList<>();

    public String getLocalVariableString() {
        return String.join("\n", localVariables);
    }

    @Override
    public void visit(VariableDeclarator variable, Void arg) {
        // Get the type as a string and add it to our list
        String typeName = variable.getType().asString();
        localVariables.add(typeName);
        super.visit(variable, arg);
    }

    public static void main(String[] args) throws IOException {
        if (args.length < 2) {
            System.err.println("Please provide 2 arguments");
            return;
        }
        FileReader inputFile = new FileReader(args[0]);
        CompilationUnit cu = StaticJavaParser.parse(inputFile);
        LocalVariableTypeCollector lvtc = new LocalVariableTypeCollector();
        lvtc.visit(cu, null);

        FileWriter outFile = new FileWriter(args[1]);
        outFile.write(lvtc.getLocalVariableString());
        outFile.close();
    }
}
